"""PlannerAgent: one turn of "produce a plan or ask for clarification", as an AgentMessage.

Composes the prompt template, an injected LLMClient (llama.cpp or Ollama — this agent doesn't
care which), and the response parser. Multi-turn orchestration — calling this repeatedly across
an agent loop, managing a ContextManager, retries/escalation — is Phase 7's job; this is the
single-call building block that wires up to.

`max_tokens` defaults to 1024, not the ~512 that would fit REQUIREMENTS.md §6's response
reserve exactly: verified live against the real local model (DeepSeek-R1-Distill-Qwen-1.5B),
its reasoning prefix alone regularly runs past 1000 tokens before it reaches an answer, so a
tighter budget would truncate every response before parse_plan_response ever saw real JSON.
Even at 1200 tokens live, this small model's reasoning was sometimes too unfocused to reach a
complete answer at all — parse_plan_response fails loudly in that case rather than guessing, but
the underlying model-quality limitation (raw /completion, no chat template, no few-shot
examples) is a real, open follow-up for the Phase 10 evaluation harness to measure systematically
rather than something to keep hand-tuning here.
"""

import httpx

from multiagent.agents.planner.prompts import render_planner_prompt
from multiagent.agents.planner.response_parser import PlanParsingError, parse_plan_response
from multiagent.agents.planner.review_parser import (
    StepReviewParsingError,
    parse_step_review_response,
)
from multiagent.agents.planner.review_prompts import render_review_prompt
from multiagent.contracts.messages import (
    AgentMessage,
    AgentName,
    CodeChangeReport,
    MessageStatus,
    PlanStep,
)
from multiagent.llm.base import LLMClient


class PlannerAgent:
    """Turns a goal (and optional existing-code context) into a Plan or a clarification request."""

    def __init__(self, llm_client: LLMClient, task_id: str, max_tokens: int = 1024):
        if max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        self._llm_client = llm_client
        self._task_id = task_id
        self._max_tokens = max_tokens

    def create_plan(self, goal: str, code_context: str = "") -> AgentMessage:
        prompt = render_planner_prompt(goal=goal, code_context=code_context)

        try:
            response = self._llm_client.generate(prompt, max_tokens=self._max_tokens)
        except httpx.HTTPError as exc:
            return AgentMessage(
                agent=AgentName.PLANNER,
                task_id=self._task_id,
                status=MessageStatus.ERROR,
                error=f"planner LLM call failed: {exc}",
            )

        try:
            plan = parse_plan_response(response.text)
        except PlanParsingError as exc:
            return AgentMessage(
                agent=AgentName.PLANNER,
                task_id=self._task_id,
                status=MessageStatus.ERROR,
                error=str(exc),
            )

        if plan.steps:
            status = MessageStatus.OK
        elif plan.clarifying_questions:
            status = MessageStatus.NEEDS_CLARIFICATION
        else:
            return AgentMessage(
                agent=AgentName.PLANNER,
                task_id=self._task_id,
                status=MessageStatus.ERROR,
                error="planner returned an empty plan with no steps and no clarifying questions",
            )

        return AgentMessage(agent=AgentName.PLANNER, task_id=self._task_id, status=status, payload=plan)

    def review_step(
        self, step: PlanStep, report: CodeChangeReport, code_context: str = ""
    ) -> AgentMessage:
        """Review one completed step. Both an approval and a rejection are status "ok" — a
        rejection is useful information for the orchestrator's retry policy, not a system error,
        the same way the Coder's own tests_passed=False isn't one either."""
        prompt = render_review_prompt(step=step, report=report, code_context=code_context)

        try:
            response = self._llm_client.generate(prompt, max_tokens=self._max_tokens)
        except httpx.HTTPError as exc:
            return AgentMessage(
                agent=AgentName.PLANNER,
                task_id=self._task_id,
                status=MessageStatus.ERROR,
                error=f"planner LLM call failed: {exc}",
            )

        try:
            review = parse_step_review_response(response.text)
        except StepReviewParsingError as exc:
            return AgentMessage(
                agent=AgentName.PLANNER,
                task_id=self._task_id,
                status=MessageStatus.ERROR,
                error=str(exc),
            )

        return AgentMessage(agent=AgentName.PLANNER, task_id=self._task_id, status=MessageStatus.OK, payload=review)
