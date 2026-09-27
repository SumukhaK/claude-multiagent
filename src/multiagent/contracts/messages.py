"""Strict, validated JSON contract for every message passed between the orchestrator and a
sub-agent. See REQUIREMENTS.md §4 — nothing here is a free-form dict, so a malformed message
fails validation loudly instead of silently corrupting the agent loop.
"""

from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator


class AgentName(str, Enum):
    """The three sub-agents the orchestrator can address."""

    PLANNER = "planner"
    CODER = "coder"
    TOOL = "tool"


class MessageStatus(str, Enum):
    """Outcome of a sub-agent's turn, as reported back to the orchestrator."""

    OK = "ok"
    NEEDS_CLARIFICATION = "needs_clarification"
    BLOCKED = "blocked"
    ERROR = "error"


class PlanStep(BaseModel):
    """One actionable step in the Planning agent's plan."""

    step_id: int
    description: str
    edge_cases: list[str] = Field(default_factory=list)


class Plan(BaseModel):
    """The Planning agent's output: a step-by-step plan for the Coding agent."""

    kind: Literal["plan"] = "plan"
    goal: str
    steps: list[PlanStep]
    clarifying_questions: list[str] = Field(default_factory=list)


class CodeChangeReport(BaseModel):
    """The Coding agent's report on one completed plan step."""

    kind: Literal["code_change_report"] = "code_change_report"
    step_id: int
    files_changed: list[str]
    tests_added: list[str]
    tests_passed: bool
    summary: str
    # path -> content of each file written (size-capped), so the reviewer can see the code
    file_contents: dict[str, str] = Field(default_factory=dict)
    # the test runner's own output (size-capped), so a failing self-written test can be explained
    # back to the Coder on retry instead of it retrying blind
    test_output: str = ""


class ToolExecutionReport(BaseModel):
    """The Tool agent's report on one git/GitHub or hardware-test action."""

    kind: Literal["tool_execution_report"] = "tool_execution_report"
    action: str
    success: bool
    details: str = ""


class StepReview(BaseModel):
    """The Planning agent's review of one completed CodeChangeReport, before the orchestrator
    advances to the next step (CLAUDE.md §4: this review gate is mandatory, not optional)."""

    kind: Literal["step_review"] = "step_review"
    step_id: int
    approved: bool
    feedback: str


AgentPayload = Annotated[
    Plan | CodeChangeReport | ToolExecutionReport | StepReview, Field(discriminator="kind")
]


class AgentMessage(BaseModel):
    """The envelope every sub-agent response is wrapped in before reaching the orchestrator."""

    agent: AgentName
    task_id: str
    status: MessageStatus
    retry_count: int = Field(default=0, ge=0)
    error: str | None = None
    payload: AgentPayload | None = None

    @model_validator(mode="after")
    def _error_field_matches_status(self) -> "AgentMessage":
        if self.status == MessageStatus.ERROR and not self.error:
            raise ValueError("status 'error' requires a non-empty 'error' message")
        if self.status != MessageStatus.ERROR and self.error is not None:
            raise ValueError("'error' must only be set when status is 'error'")
        return self
