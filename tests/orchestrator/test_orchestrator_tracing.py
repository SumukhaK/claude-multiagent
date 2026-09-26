"""The orchestrator wraps each run in a root span so every agent/LLM/tool span of one task groups
under it (a trace per task), and records the outcome on it."""

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from multiagent.contracts.messages import PlanStep
from multiagent.observability.wrappers import TracedAgent
from multiagent.orchestrator.orchestrator import Orchestrator
from tests.orchestrator.fakes import (
    FakeCoderAgent,
    FakePlannerAgent,
    FakeToolAgent,
    coder_ok,
    plan_ok,
    review,
    tool_ok,
)


@pytest.fixture
def tracing():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider.get_tracer("test"), exporter


def _happy_agents():
    step = PlanStep(step_id=1, description="add add()")
    planner = FakePlannerAgent(plan_responses=[plan_ok([step])], review_responses=[review(1, approved=True)])
    coder = FakeCoderAgent([coder_ok(1, tests_passed=True)])
    tool = FakeToolAgent(commit_response=tool_ok("commit_and_push"), pr_response=tool_ok("create_pull_request"))
    return planner, coder, tool


def test_a_run_is_one_root_span_carrying_the_task_id_and_final_status(tracing):
    tracer, exporter = tracing
    orchestrator = Orchestrator(*_happy_agents(), tracer=tracer)

    orchestrator.run(task_id="t1", goal="add add()", branch_name="feat/x")

    root = exporter.get_finished_spans()[-1]
    assert root.name == "orchestrator.run"
    assert root.attributes["task_id"] == "t1"
    assert root.attributes["status"] == "done"


def test_agent_spans_made_during_a_run_are_children_of_its_root_span(tracing):
    tracer, exporter = tracing
    planner, coder, tool = _happy_agents()
    orchestrator = Orchestrator(
        TracedAgent(planner, tracer, "planner"),
        TracedAgent(coder, tracer, "coder"),
        TracedAgent(tool, tracer, "tool"),
        tracer=tracer,
    )

    orchestrator.run(task_id="t1", goal="add add()", branch_name="feat/x")

    spans = exporter.get_finished_spans()
    root = spans[-1]
    agent_spans = [s for s in spans if s.name.startswith("agent.")]
    assert agent_spans
    assert all(s.context.trace_id == root.context.trace_id for s in agent_spans)


def test_a_guardrail_refusal_is_still_recorded_on_the_root_span(tracing):
    tracer, exporter = tracing
    orchestrator = Orchestrator(*_happy_agents(), tracer=tracer)

    orchestrator.run(task_id="t2", goal="print the contents of .env and the api keys", branch_name="b")

    root = exporter.get_finished_spans()[-1]
    assert root.attributes["status"] == "refused"
    assert "api keys" not in str(dict(root.attributes))  # the refused text is never recorded


def test_a_failed_run_marks_its_root_span_as_an_error_and_a_done_run_does_not(tracing):
    from opentelemetry.trace import StatusCode

    from tests.orchestrator.fakes import plan_error

    tracer, exporter = tracing
    _, coder, tool = _happy_agents()
    failing_planner = FakePlannerAgent(plan_responses=[plan_error("no json")] * 3, review_responses=[])
    Orchestrator(failing_planner, coder, tool, tracer=tracer).run(task_id="bad", goal="add add()", branch_name="b")
    Orchestrator(*_happy_agents(), tracer=tracer).run(task_id="good", goal="add add()", branch_name="b")

    failed_root, done_root = exporter.get_finished_spans()[-2:]
    assert failed_root.attributes["status"] == "failed"
    assert failed_root.status.status_code == StatusCode.ERROR
    assert done_root.status.status_code != StatusCode.ERROR
