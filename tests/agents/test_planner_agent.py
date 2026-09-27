"""Tests for PlannerAgent: composes the prompt template, an LLMClient, and the response parser
into the single operation "produce a plan or ask for clarification", reported as an AgentMessage.

The multi-turn orchestration loop (calling this repeatedly, managing a ContextManager across
turns, retries) is Phase 7's job — this is the single-call building block Phase 7 will wire up.
"""

import httpx
import pytest

from multiagent.agents.planner.agent import PlannerAgent
from multiagent.contracts.messages import (
    AgentName,
    CodeChangeReport,
    MessageStatus,
    Plan,
    PlanStep,
    StepReview,
)
from multiagent.llm.base import LLMResponse


class FakeLLMClient:
    def __init__(self, text: str = "", error: Exception | None = None):
        self._text = text
        self._error = error
        self.last_prompt: str | None = None
        self.last_json_schema: dict | None = None

    def generate(
        self, prompt: str, *, max_tokens: int = 512, json_schema: dict | None = None
    ) -> LLMResponse:
        self.last_prompt = prompt
        self.last_json_schema = json_schema
        if self._error is not None:
            raise self._error
        return LLMResponse(text=self._text, prompt_tokens=10, completion_tokens=10, latency_seconds=0.1)


def test_create_plan_returns_ok_with_parsed_plan_when_steps_are_present():
    llm = FakeLLMClient(
        text='{"kind": "plan", "goal": "add health endpoint", '
        '"steps": [{"step_id": 1, "description": "write a failing test", "edge_cases": []}], '
        '"clarifying_questions": []}'
    )
    agent = PlannerAgent(llm_client=llm, task_id="task-1")

    message = agent.create_plan(goal="add health endpoint")

    assert message.agent == AgentName.PLANNER
    assert message.status == MessageStatus.OK
    assert isinstance(message.payload, Plan)
    assert message.payload.steps[0].description == "write a failing test"
    assert "add health endpoint" in llm.last_prompt


def test_create_plan_returns_needs_clarification_when_steps_are_empty_with_questions():
    llm = FakeLLMClient(
        text='{"kind": "plan", "goal": "fix the bug", "steps": [], '
        '"clarifying_questions": ["which endpoint is affected?"]}'
    )
    agent = PlannerAgent(llm_client=llm, task_id="task-1")

    message = agent.create_plan(goal="fix the bug")

    assert message.status == MessageStatus.NEEDS_CLARIFICATION
    assert message.payload.clarifying_questions == ["which endpoint is affected?"]


def test_create_plan_returns_error_when_the_llm_call_fails():
    llm = FakeLLMClient(error=httpx.ConnectError("connection refused"))
    agent = PlannerAgent(llm_client=llm, task_id="task-1")

    message = agent.create_plan(goal="fix the bug")

    assert message.status == MessageStatus.ERROR
    assert message.error is not None
    assert message.payload is None


def test_create_plan_returns_error_when_the_response_cannot_be_parsed():
    llm = FakeLLMClient(text="I don't think I can help with that.")
    agent = PlannerAgent(llm_client=llm, task_id="task-1")

    message = agent.create_plan(goal="fix the bug")

    assert message.status == MessageStatus.ERROR
    assert message.error is not None


def test_create_plan_strips_a_think_block_from_a_reasoning_model_before_parsing():
    llm = FakeLLMClient(
        text="<think>the user wants a health endpoint</think>"
        '{"kind": "plan", "goal": "add health endpoint", "steps": [], '
        '"clarifying_questions": ["which framework?"]}'
    )
    agent = PlannerAgent(llm_client=llm, task_id="task-1")

    message = agent.create_plan(goal="add health endpoint")

    assert message.status == MessageStatus.NEEDS_CLARIFICATION
    assert message.payload.clarifying_questions == ["which framework?"]


def test_create_plan_returns_error_for_an_empty_plan_with_no_questions():
    """No steps and no clarifying questions is a degenerate response - report it as an error
    rather than silently treating it as a completed (but empty) plan."""
    llm = FakeLLMClient(text='{"kind": "plan", "goal": "fix it", "steps": [], "clarifying_questions": []}')
    agent = PlannerAgent(llm_client=llm, task_id="task-1")

    message = agent.create_plan(goal="fix it")

    assert message.status == MessageStatus.ERROR
    assert message.error is not None
    assert message.payload is None


def test_create_plan_includes_code_context_in_the_prompt_when_given():
    llm = FakeLLMClient(
        text='{"kind": "plan", "goal": "fix it", "steps": [{"step_id": 1, "description": "d", "edge_cases": []}], "clarifying_questions": []}'
    )
    agent = PlannerAgent(llm_client=llm, task_id="task-1")

    agent.create_plan(goal="fix it", code_context="def broken(): pass")

    assert "def broken(): pass" in llm.last_prompt


@pytest.mark.parametrize("bad_max_tokens", [0, -1])
def test_planner_agent_rejects_a_non_positive_max_tokens_at_construction(bad_max_tokens):
    with pytest.raises(ValueError):
        PlannerAgent(llm_client=FakeLLMClient(), task_id="task-1", max_tokens=bad_max_tokens)


def _report(tests_passed: bool = True) -> CodeChangeReport:
    return CodeChangeReport(
        step_id=1,
        files_changed=["calc.py", "test_calc.py"],
        tests_added=["test_calc.py"],
        tests_passed=tests_passed,
        summary="added add()",
    )


def test_review_step_returns_ok_with_an_approved_review():
    llm = FakeLLMClient(text='{"kind": "step_review", "step_id": 1, "approved": true, "feedback": "looks correct"}')
    agent = PlannerAgent(llm_client=llm, task_id="task-1")

    message = agent.review_step(PlanStep(step_id=1, description="add add()"), _report())

    assert message.status == MessageStatus.OK
    assert isinstance(message.payload, StepReview)
    assert message.payload.approved is True


def test_review_step_returns_ok_with_a_rejected_review():
    """A rejection is a legitimate, useful outcome for the orchestrator to act on - not a system
    error, the same way a failing test run from the Coder isn't one either."""
    llm = FakeLLMClient(
        text='{"kind": "step_review", "step_id": 1, "approved": false, "feedback": "test does not cover the change"}'
    )
    agent = PlannerAgent(llm_client=llm, task_id="task-1")

    message = agent.review_step(PlanStep(step_id=1, description="add add()"), _report())

    assert message.status == MessageStatus.OK
    assert message.payload.approved is False


def test_review_step_returns_error_when_the_llm_call_fails():
    llm = FakeLLMClient(error=httpx.ConnectError("connection refused"))
    agent = PlannerAgent(llm_client=llm, task_id="task-1")

    message = agent.review_step(PlanStep(step_id=1, description="add add()"), _report())

    assert message.status == MessageStatus.ERROR


def test_review_step_returns_error_when_the_response_cannot_be_parsed():
    llm = FakeLLMClient(text="I don't think I can tell.")
    agent = PlannerAgent(llm_client=llm, task_id="task-1")

    message = agent.review_step(PlanStep(step_id=1, description="add add()"), _report())

    assert message.status == MessageStatus.ERROR


def test_review_step_includes_the_step_and_report_in_the_prompt():
    llm = FakeLLMClient(text='{"kind": "step_review", "step_id": 1, "approved": true, "feedback": "ok"}')
    agent = PlannerAgent(llm_client=llm, task_id="task-1")

    agent.review_step(PlanStep(step_id=1, description="add add()"), _report())

    assert "add add()" in llm.last_prompt


_REVIEW_TEXT = '{"kind": "step_review", "step_id": 1, "approved": true, "feedback": "ok"}'
_STEP = PlanStep(step_id=1, description="d", edge_cases=[])
_REPORT = CodeChangeReport(
    step_id=1, files_changed=["a.py"], tests_added=["test_a.py"], tests_passed=True, summary="s"
)


def test_planner_sends_no_schema_unless_constrain_json_is_enabled():
    llm = FakeLLMClient(text='{"kind": "plan", "goal": "g", "steps": [], "clarifying_questions": ["q?"]}')

    PlannerAgent(llm_client=llm, task_id="t").create_plan(goal="g")

    assert llm.last_json_schema is None


def test_planner_constrains_planning_to_the_plan_schema():
    llm = FakeLLMClient(text='{"kind": "plan", "goal": "g", "steps": [], "clarifying_questions": ["q?"]}')

    PlannerAgent(llm_client=llm, task_id="t", constrain_json=True).create_plan(goal="g")

    assert llm.last_json_schema == Plan.model_json_schema()


def test_planner_constrains_review_to_the_step_review_schema():
    llm = FakeLLMClient(text=_REVIEW_TEXT)

    PlannerAgent(llm_client=llm, task_id="t", constrain_json=True).review_step(_STEP, _REPORT)

    assert llm.last_json_schema == StepReview.model_json_schema()


def test_review_step_puts_the_goal_in_the_prompt():
    llm = FakeLLMClient(text=_REVIEW_TEXT)

    PlannerAgent(llm_client=llm, task_id="t").review_step(_STEP, _REPORT, goal="Add add(a, b) in calc.py")

    assert "Add add(a, b) in calc.py" in llm.last_prompt
