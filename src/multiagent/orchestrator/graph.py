"""The LangGraph state machine wiring the Planner, Coder, and Tool agents into the plan ->
implement -> review loop, with a human-in-the-loop clarification interrupt, bounded per-step
retries, and a hard step-budget circuit breaker.

Node functions read/update OrchestratorState; conditional-edge router functions only read it to
pick the next node (LangGraph's routing callables return a node name, they don't mutate state).

Per REQUIREMENTS.md §8: `tests_passed` is the primary, objective gate for advancing a step; the
Planner's `review_step` is consulted only when tests already passed, as an *additional* signal —
a rejection is acted on (retried), but an approval alone is never the deciding vote, since it was
verified live to rubber-stamp an explicit description/summary mismatch.

Human-in-the-loop note on `clarification_node`: LangGraph re-executes a node from its start when
resuming past an `interrupt()` call inside it. Nothing may therefore run *before* the
`interrupt()` call (no LLM call, no side effect), so resuming is cheap; the one side effect
(remembering the answer) sits after it and runs exactly once. The actual re-planning work happens
in `plan_node`, which the graph loops back to afterwards.

Memory (Phase 8): recalled memory is appended to the code context handed to the Planner, Coder
and reviewer. Only *verified* outcomes are remembered -- an approved step (tests passed), a user
clarification, a completed task -- never plans (unverified proposals) or failed attempts, which
would poison future recall. Memory calls are not orchestration steps and don't spend the budget.
"""

from collections.abc import Sequence
from typing import Protocol

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from multiagent.contracts.messages import (
    AgentMessage,
    CodeChangeReport,
    MessageStatus,
    Plan,
    PlanStep,
)
from multiagent.orchestrator.state import OrchestratorState


class PlannerAgentProtocol(Protocol):
    def create_plan(self, goal: str, code_context: str = "") -> AgentMessage: ...
    def review_step(
        self, step: PlanStep, report: CodeChangeReport, code_context: str = ""
    ) -> AgentMessage: ...


class CoderAgentProtocol(Protocol):
    def implement_step(self, step: PlanStep, code_context: str = "") -> AgentMessage: ...


class MemoryProtocol(Protocol):
    def recall_context(self, query: str) -> str: ...
    def remember(self, text: str, kind: str) -> bool: ...


class ToolAgentProtocol(Protocol):
    def commit_and_push(self, branch: str, summary: str, paths: Sequence[str]) -> AgentMessage: ...
    def open_pull_request(self, title: str, body: str, base: str = "main") -> AgentMessage: ...


def build_orchestrator_graph(
    planner_agent: PlannerAgentProtocol,
    coder_agent: CoderAgentProtocol,
    tool_agent: ToolAgentProtocol,
    max_retries_per_step: int,
    max_orchestrator_steps: int,
    memory: MemoryProtocol | None = None,
) -> StateGraph:
    """Build the (uncompiled-then-compiled) graph. The caller supplies the checkpointer at
    compile time via `.compile(checkpointer=...)` — this function does the wiring only."""

    def over_budget(state: OrchestratorState) -> bool:
        return state["step_count"] >= max_orchestrator_steps

    def context_for(state: OrchestratorState, query: str) -> str:
        """The caller's code context plus any recalled memory relevant to `query` (already
        size-capped and guardrail-wrapped by the memory store)."""
        base = state.get("code_context", "")
        recalled = memory.recall_context(query) if memory is not None else ""
        return f"{base}\n\n{recalled}" if base and recalled else base or recalled

    def remember(text: str, kind: str) -> None:
        if memory is not None:
            memory.remember(text, kind)

    def plan_node(state: OrchestratorState) -> dict:
        goal = state["goal"]
        if state.get("clarification_answer"):
            goal = f"{goal}\n\nUser clarification: {state['clarification_answer']}"
        message = planner_agent.create_plan(goal, context_for(state, goal))
        step_count = state["step_count"] + 1
        if message.status == MessageStatus.OK:
            assert isinstance(message.payload, Plan)
            return {
                "plan": message.payload,
                "planner_error": None,
                "plan_retry_count": 0,
                "clarifying_questions": None,
                "step_count": step_count,
            }
        if message.status == MessageStatus.NEEDS_CLARIFICATION:
            assert isinstance(message.payload, Plan)
            return {
                "clarifying_questions": message.payload.clarifying_questions,
                "planner_error": None,
                "plan_retry_count": 0,
                "step_count": step_count,
            }
        return {
            "planner_error": message.error,
            "plan_retry_count": state["plan_retry_count"] + 1,
            "step_count": step_count,
        }

    def route_after_plan(state: OrchestratorState) -> str:
        if over_budget(state):
            return "escalate_node"
        if state.get("planner_error"):
            if state["plan_retry_count"] > max_retries_per_step:
                return "escalate_node"
            return "plan_node"
        if state.get("plan") is not None:
            return "implement_step_node"
        return "clarification_node"

    def clarification_node(state: OrchestratorState) -> dict:
        questions = state.get("clarifying_questions") or []
        answer = interrupt({"questions": questions})
        # After the interrupt, so it runs exactly once: the first execution raises at interrupt().
        remember(f"Clarification. Questions: {'; '.join(questions)} User answered: {answer}", "clarification")
        return {"clarification_answer": answer}

    def implement_step_node(state: OrchestratorState) -> dict:
        assert state["plan"] is not None
        step = state["plan"].steps[state["current_step_index"]]
        message = coder_agent.implement_step(step, context_for(state, step.description))
        step_count = state["step_count"] + 1
        if message.status == MessageStatus.ERROR:
            return {
                "coder_error": message.error,
                "step_retry_count": state["step_retry_count"] + 1,
                "step_count": step_count,
            }
        assert isinstance(message.payload, CodeChangeReport)
        return {
            "step_reports": [*state["step_reports"], message.payload],
            "coder_error": None,
            "step_count": step_count,
        }

    def route_after_implement(state: OrchestratorState) -> str:
        if over_budget(state):
            return "escalate_node"
        if state.get("coder_error"):
            if state["step_retry_count"] > max_retries_per_step:
                return "escalate_node"
            return "implement_step_node"
        return "review_step_node"

    def review_step_node(state: OrchestratorState) -> dict:
        assert state["plan"] is not None
        report = state["step_reports"][-1]
        step = state["plan"].steps[state["current_step_index"]]
        step_count = state["step_count"] + 1

        approved = report.tests_passed
        if report.tests_passed:
            review_message = planner_agent.review_step(step, report, context_for(state, step.description))
            if review_message.status == MessageStatus.OK and not review_message.payload.approved:
                approved = False

        if approved:
            remember(
                f"Step {step.step_id} ({step.description}) completed: {report.summary} "
                f"Files: {', '.join(report.files_changed)}",
                "step_summary",
            )
            return {
                "current_step_index": state["current_step_index"] + 1,
                "step_retry_count": 0,
                "last_step_approved": True,
                "step_count": step_count,
            }
        return {
            "step_retry_count": state["step_retry_count"] + 1,
            "last_step_approved": False,
            "step_count": step_count,
        }

    def route_after_review(state: OrchestratorState) -> str:
        if over_budget(state):
            return "escalate_node"
        if state["last_step_approved"]:
            assert state["plan"] is not None
            if state["current_step_index"] >= len(state["plan"].steps):
                return "tool_node"
            return "implement_step_node"
        if state["step_retry_count"] > max_retries_per_step:
            return "escalate_node"
        return "implement_step_node"

    def tool_node(state: OrchestratorState) -> dict:
        all_files = sorted({path for report in state["step_reports"] for path in report.files_changed})
        summary = "; ".join(report.summary for report in state["step_reports"])
        step_count = state["step_count"] + 1

        commit_message = tool_agent.commit_and_push(branch=state["branch_name"], summary=summary, paths=all_files)
        if commit_message.status == MessageStatus.ERROR:
            return {"tool_error": commit_message.error, "step_count": step_count}

        pr_message = tool_agent.open_pull_request(
            title=f"feat: {state['goal']}",
            body="\n".join(f"- {report.summary}" for report in state["step_reports"]),
        )
        step_count += 1
        if pr_message.status == MessageStatus.ERROR:
            return {"tool_error": pr_message.error, "step_count": step_count}
        return {"pr_details": pr_message.payload.details, "tool_error": None, "step_count": step_count}

    def route_after_tool(state: OrchestratorState) -> str:
        if state.get("tool_error"):
            return "escalate_node"
        return "done_node"

    def escalate_node(state: OrchestratorState) -> dict:
        if over_budget(state):
            message = f"escalated: step budget exceeded ({state['step_count']}/{max_orchestrator_steps} steps)"
        elif state.get("planner_error"):
            message = (
                f"escalated: planner error after {state['plan_retry_count']} retries: "
                f"{state['planner_error']}"
            )
        elif state.get("coder_error"):
            message = f"escalated: coder error after {state['step_retry_count']} retries: {state['coder_error']}"
        elif state.get("tool_error"):
            message = f"escalated: tool error: {state['tool_error']}"
        elif state.get("last_step_approved") is False:
            message = (
                f"escalated: step {state['current_step_index']} failed review/tests "
                f"after {state['step_retry_count']} retries"
            )
        else:
            message = "escalated: unknown failure"
        return {"status": "failed", "error": message}

    def done_node(state: OrchestratorState) -> dict:
        remember(
            f"Completed task: {state['goal']} (branch {state['branch_name']}, "
            f"{len(state['plan'].steps)} steps)",
            "task",
        )
        return {"status": "done"}

    graph = StateGraph(OrchestratorState)
    graph.add_node("plan_node", plan_node)
    graph.add_node("clarification_node", clarification_node)
    graph.add_node("implement_step_node", implement_step_node)
    graph.add_node("review_step_node", review_step_node)
    graph.add_node("tool_node", tool_node)
    graph.add_node("escalate_node", escalate_node)
    graph.add_node("done_node", done_node)

    graph.add_edge(START, "plan_node")
    graph.add_conditional_edges("plan_node", route_after_plan)
    graph.add_edge("clarification_node", "plan_node")
    graph.add_conditional_edges("implement_step_node", route_after_implement)
    graph.add_conditional_edges("review_step_node", route_after_review)
    graph.add_conditional_edges("tool_node", route_after_tool)
    graph.add_edge("escalate_node", END)
    graph.add_edge("done_node", END)

    return graph
