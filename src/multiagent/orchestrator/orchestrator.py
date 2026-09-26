"""Orchestrator: the public entry point wrapping the compiled LangGraph state machine.

Hides LangGraph-specific mechanics (thread_id config, Command/interrupt plumbing) behind a
plain `run`/`resume` API. Uses an in-memory checkpointer by default — per-run state only needs
to survive for the lifetime of one process (there's no requirement to resume a task across a
restart), so no external database is needed, matching the project's local-first, free-tier-only
constraint.
"""

import logging
from collections.abc import Callable
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from opentelemetry.trace import Status, StatusCode, Tracer

from multiagent.guardrails.input_filter import check_user_input
from multiagent.orchestrator.graph import (
    CoderAgentProtocol,
    MemoryProtocol,
    PlannerAgentProtocol,
    ToolAgentProtocol,
    build_orchestrator_graph,
)
from multiagent.observability.tracing import get_tracer
from multiagent.orchestrator.state import build_initial_state

logger = logging.getLogger(__name__)


class Orchestrator:
    """Runs the plan -> implement -> review -> tool-action loop for one task at a time."""

    def __init__(
        self,
        planner_agent: PlannerAgentProtocol,
        coder_agent: CoderAgentProtocol,
        tool_agent: ToolAgentProtocol,
        max_retries_per_step: int = 2,
        max_orchestrator_steps: int = 25,
        memory: MemoryProtocol | None = None,
        tracer: Tracer | None = None,
    ):
        self._tracer = tracer or get_tracer()
        graph = build_orchestrator_graph(
            planner_agent, coder_agent, tool_agent, max_retries_per_step, max_orchestrator_steps, memory
        )
        self._compiled = graph.compile(checkpointer=MemorySaver())

    @staticmethod
    def _refuse_if_disallowed(user_text: str) -> dict[str, Any] | None:
        """Guardrail on everything the user types (the goal and every clarification answer),
        checked before any agent sees it. Logs the category only, never the text: it may itself
        contain the secret being refused."""
        verdict = check_user_input(user_text)
        if verdict.allowed:
            return None
        logger.warning("input refused by guardrail (%s)", verdict.category)
        return {"status": "refused", "error": verdict.reason, "category": verdict.category}

    def run(self, task_id: str, goal: str, branch_name: str, code_context: str = "") -> dict[str, Any]:
        def start() -> dict[str, Any]:
            if refusal := self._refuse_if_disallowed(goal):
                return refusal
            config = {"configurable": {"thread_id": task_id}}
            initial_state = build_initial_state(
                task_id=task_id, goal=goal, branch_name=branch_name, code_context=code_context
            )
            return self._compiled.invoke(initial_state, config)

        return self._in_root_span("orchestrator.run", task_id, start)

    def resume(self, task_id: str, answer: str) -> dict[str, Any]:
        def carry_on() -> dict[str, Any]:
            # A refused answer never reaches the graph, so the task stays paused waiting for a proper one.
            if refusal := self._refuse_if_disallowed(answer):
                return refusal
            config = {"configurable": {"thread_id": task_id}}
            return self._compiled.invoke(Command(resume=answer), config)

        return self._in_root_span("orchestrator.resume", task_id, carry_on)

    def _in_root_span(self, name: str, task_id: str, action: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        """One root span per call, so every agent/LLM/tool span it causes shares one trace. Records
        the outcome (never the goal or answer text, which may hold what the guardrail refused)."""
        with self._tracer.start_as_current_span(name, attributes={"task_id": task_id}) as span:
            result = action()
            status = "needs_clarification" if "__interrupt__" in result else result.get("status", "unknown")
            span.set_attribute("status", status)
            if status == "failed":
                span.set_status(Status(StatusCode.ERROR, "orchestrator run failed"))
            return result

    def needs_clarification(self, result: dict[str, Any]) -> bool:
        return "__interrupt__" in result

    def clarifying_questions(self, result: dict[str, Any]) -> list[str]:
        interrupts = result["__interrupt__"]
        return interrupts[0].value.get("questions", [])
