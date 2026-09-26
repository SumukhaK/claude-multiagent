"""Shared state that flows through the orchestrator's LangGraph state machine.

Node functions read and update this state; conditional-edge router functions only read it to
decide the next node — LangGraph's `add_conditional_edges` path callables return a node name,
not a state update, so all state mutation happens inside nodes (CLAUDE.md-consistent: explicit,
not magic reducers).
"""

from typing import TypedDict

from multiagent.contracts.messages import CodeChangeReport, Plan


class OrchestratorState(TypedDict):
    task_id: str
    goal: str
    code_context: str
    branch_name: str

    clarification_answer: str | None
    clarifying_questions: list[str] | None

    plan: Plan | None
    plan_retry_count: int
    current_step_index: int
    step_reports: list[CodeChangeReport]
    step_retry_count: int
    last_step_approved: bool | None

    step_count: int
    status: str
    error: str | None

    planner_error: str | None
    coder_error: str | None
    tool_error: str | None
    pr_details: str | None


def build_initial_state(task_id: str, goal: str, branch_name: str, code_context: str = "") -> OrchestratorState:
    return OrchestratorState(
        task_id=task_id,
        goal=goal,
        code_context=code_context,
        branch_name=branch_name,
        clarification_answer=None,
        clarifying_questions=None,
        plan=None,
        plan_retry_count=0,
        current_step_index=0,
        step_reports=[],
        step_retry_count=0,
        last_step_approved=None,
        step_count=0,
        status="running",
        error=None,
        planner_error=None,
        coder_error=None,
        tool_error=None,
        pr_details=None,
    )
