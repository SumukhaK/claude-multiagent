"""Orchestrator: the public entry point wrapping the compiled LangGraph state machine.

Hides LangGraph-specific mechanics (thread_id config, Command/interrupt plumbing) behind a
plain `run`/`resume` API. Uses an in-memory checkpointer by default — per-run state only needs
to survive for the lifetime of one process (there's no requirement to resume a task across a
restart), so no external database is needed, matching the project's local-first, free-tier-only
constraint.
"""

from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from multiagent.orchestrator.graph import (
    CoderAgentProtocol,
    MemoryProtocol,
    PlannerAgentProtocol,
    ToolAgentProtocol,
    build_orchestrator_graph,
)
from multiagent.orchestrator.state import build_initial_state


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
    ):
        graph = build_orchestrator_graph(
            planner_agent, coder_agent, tool_agent, max_retries_per_step, max_orchestrator_steps, memory
        )
        self._compiled = graph.compile(checkpointer=MemorySaver())

    def run(self, task_id: str, goal: str, branch_name: str, code_context: str = "") -> dict[str, Any]:
        config = {"configurable": {"thread_id": task_id}}
        initial_state = build_initial_state(
            task_id=task_id, goal=goal, branch_name=branch_name, code_context=code_context
        )
        return self._compiled.invoke(initial_state, config)

    def resume(self, task_id: str, answer: str) -> dict[str, Any]:
        config = {"configurable": {"thread_id": task_id}}
        return self._compiled.invoke(Command(resume=answer), config)

    def needs_clarification(self, result: dict[str, Any]) -> bool:
        return "__interrupt__" in result

    def clarifying_questions(self, result: dict[str, Any]) -> list[str]:
        interrupts = result["__interrupt__"]
        return interrupts[0].value.get("questions", [])
