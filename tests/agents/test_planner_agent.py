"""Tests for PlannerAgent: composes the prompt template, an LLMClient, and the response parser
into the single operation "produce a plan or ask for clarification", reported as an AgentMessage.

The multi-turn orchestration loop (calling this repeatedly, managing a ContextManager across
turns, retries) is Phase 7's job — this is the single-call building block Phase 7 will wire up.
"""

import httpx
import pytest

from multiagent.agents.planner.agent import PlannerAgent
from multiagent.contracts.messages import AgentName, MessageStatus, Plan
from multiagent.llm.base import LLMResponse


class FakeLLMClient:
    def __init__(self, text: str = "", error: Exception | None = None):
        self._text = text
        self._error = error
        self.last_prompt: str | None = None

    def generate(self, prompt: str, *, max_tokens: int = 512) -> LLMResponse:
        self.last_prompt = prompt
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
        '{"kind": "plan", "goal": "add health endpoint", "steps": [], "clarifying_questions": []}'
    )
    agent = PlannerAgent(llm_client=llm, task_id="task-1")

    message = agent.create_plan(goal="add health endpoint")

    # empty steps and no clarifying_questions is unusual but not invalid - still reported as ok
    assert message.status == MessageStatus.OK


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
