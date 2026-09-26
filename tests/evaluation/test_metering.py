"""Tests for the metering wrappers the evaluation uses to observe a run without changing it.

The agents take their LLM client and tools by injection, so metering is done by wrapping those
objects -- no agent code changes, and the same wrappers work against fakes in tests and the real
models in an actual evaluation run.
"""

import pytest

from multiagent.contracts.messages import PlanStep
from multiagent.evaluation.metering import Meter, MeteredAgent, MeteredLLMClient, MeteredTools
from multiagent.llm.base import LLMResponse
from multiagent.tools.git_tools import ToolCommandResult
from tests.orchestrator.fakes import (
    FakeCoderAgent,
    FakePlannerAgent,
    FakeToolAgent,
    coder_error,
    coder_ok,
    make_orchestrator,
    plan_needs_clarification,
    plan_ok,
    review,
    tool_ok,
)


class FakeLLM:
    def __init__(self, response=None, error=None):
        self._response = response
        self._error = error

    def generate(self, prompt, *, max_tokens=512):
        if self._error:
            raise self._error
        return self._response


def test_llm_client_records_tokens_latency_and_role_and_returns_the_response_unchanged():
    meter = Meter()
    response = LLMResponse(text="hi", prompt_tokens=30, completion_tokens=12, latency_seconds=1.5)

    result = MeteredLLMClient(FakeLLM(response), meter, role="planner").generate("p", max_tokens=64)

    assert result is response
    call = meter.llm_calls[0]
    assert (call.role, call.prompt_tokens, call.completion_tokens, call.latency_seconds) == ("planner", 30, 12, 1.5)
    assert call.error is None


def test_llm_client_records_a_failed_call_and_reraises():
    meter = Meter()

    with pytest.raises(ConnectionError):
        MeteredLLMClient(FakeLLM(error=ConnectionError("down")), meter, role="coder").generate("p")

    assert meter.llm_calls[0].error == "down"
    assert meter.llm_calls[0].completion_tokens == 0


def test_total_tokens_sums_prompt_and_completion_across_roles():
    meter = Meter()
    for role, prompt_tokens, completion_tokens in [("planner", 10, 5), ("coder", 20, 7)]:
        resp = LLMResponse("x", prompt_tokens, completion_tokens, 0.1)
        MeteredLLMClient(FakeLLM(resp), meter, role=role).generate("p")

    assert meter.total_tokens() == 42
    assert meter.total_tokens(role="coder") == 27


def test_agent_wrapper_records_status_error_and_test_outcome_and_passes_the_message_through():
    meter = Meter()
    coder = MeteredAgent(FakeCoderAgent([coder_ok(1, tests_passed=False), coder_error("boom")]), meter, "coder")
    step = PlanStep(step_id=1, description="d")

    first = coder.implement_step(step, "ctx")
    second = coder.implement_step(step)

    assert first.payload.tests_passed is False  # the wrapped agent's own message, untouched
    assert [c.status for c in meter.agent_calls] == ["ok", "error"]
    assert meter.agent_calls[0].tests_passed is False
    assert meter.agent_calls[1].error == "boom"
    assert meter.agent_calls[1].tests_passed is None
    assert second.error == "boom"


def test_agent_wrapper_records_needs_clarification():
    meter = Meter()
    planner = MeteredAgent(FakePlannerAgent([plan_needs_clarification(["which?"])]), meter, "planner")

    planner.create_plan("goal")

    assert meter.agent_calls[0].status == "needs_clarification"
    assert meter.agent_calls[0].method == "create_plan"


def test_agent_wrapper_records_an_exception_and_reraises():
    class Exploding:
        def create_plan(self, goal, code_context=""):
            raise RuntimeError("bug")

    meter = Meter()

    with pytest.raises(RuntimeError):
        MeteredAgent(Exploding(), meter, "planner").create_plan("goal")

    assert meter.agent_calls[0].status == "exception"
    assert meter.agent_calls[0].error == "bug"


def test_tool_wrapper_records_each_operation_with_success_and_timeout():
    class FakeGit:
        def push(self, branch):
            return ToolCommandResult(success=False, return_code=-1, output="", duration_seconds=1.0, timed_out=True)

        def commit(self, message, paths):
            return ToolCommandResult(success=True, return_code=0, output="", duration_seconds=0.1)

    meter = Meter()
    git = MeteredTools(FakeGit(), meter)

    git.commit("m", ["a.py"])
    git.push("b")

    assert [(c.operation, c.success, c.timed_out) for c in meter.tool_calls] == [
        ("commit", True, False),
        ("push", False, True),
    ]


def test_tool_wrapper_records_a_raised_precondition_error_as_a_failure_and_reraises():
    class FakeGit:
        def commit(self, message, paths):
            raise ValueError("commit message must not be empty")

    meter = Meter()

    with pytest.raises(ValueError):
        MeteredTools(FakeGit(), meter).commit("", [])

    assert meter.tool_calls[0].success is False


def test_the_real_orchestrator_runs_unchanged_through_metered_agents():
    step = PlanStep(step_id=1, description="add add()")
    meter = Meter()
    planner = MeteredAgent(FakePlannerAgent([plan_ok([step])], [review(1, approved=True)]), meter, "planner")
    coder = MeteredAgent(FakeCoderAgent([coder_ok(1, tests_passed=True)]), meter, "coder")
    tool = MeteredAgent(FakeToolAgent(tool_ok("commit_and_push"), tool_ok("create_pull_request")), meter, "tool")

    result = make_orchestrator(planner, coder, tool).run(task_id="t", goal="add add()", branch_name="feat/x")

    assert result["status"] == "done"
    assert [(c.agent, c.method) for c in meter.agent_calls] == [
        ("planner", "create_plan"),
        ("coder", "implement_step"),
        ("planner", "review_step"),
        ("tool", "commit_and_push"),
        ("tool", "open_pull_request"),
    ]


def test_llm_client_passes_a_json_schema_through_only_when_one_is_given():
    seen = []

    class Recording:
        def generate(self, prompt, **kwargs):
            seen.append(kwargs)
            return LLMResponse(text="", prompt_tokens=0, completion_tokens=0, latency_seconds=0)

    client = MeteredLLMClient(Recording(), Meter(), role="planner")
    client.generate("p", max_tokens=8)
    client.generate("p", max_tokens=8, json_schema={"type": "object"})

    assert seen == [{"max_tokens": 8}, {"max_tokens": 8, "json_schema": {"type": "object"}}]
