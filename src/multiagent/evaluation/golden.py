"""The shape of one golden evaluation task.

A golden task is a fixed goal with an objective, hidden way to judge the result. The acceptance
test is never shown to any agent (it is written into the sandbox only after the run), so success
is judged by evidence rather than by the model's own report.
"""

from dataclasses import dataclass, field

_CATEGORIES = {"feature", "bugfix", "clarification", "adversarial"}
_EXPECTATIONS = {"implement", "refuse"}


@dataclass(frozen=True)
class GoldenTask:
    id: str
    category: str
    goal: str
    expectation: str  # "implement": should produce working code; "refuse": the guardrail should stop it
    acceptance_test: str = ""  # hidden pytest file; empty for tasks that should be refused
    seed_files: dict[str, str] = field(default_factory=dict)  # existing code the agents can see
    reference_solution: dict[str, str] = field(default_factory=dict)  # proves the test is satisfiable
    clarification_answer: str | None = None  # given if the Planner asks a question

    def __post_init__(self) -> None:
        if self.category not in _CATEGORIES:
            raise ValueError(f"unknown category {self.category!r}")
        if self.expectation not in _EXPECTATIONS:
            raise ValueError(f"unknown expectation {self.expectation!r}")
        if self.expectation == "implement" and not (self.acceptance_test and self.reference_solution):
            raise ValueError(f"{self.id}: an implementation task needs an acceptance test and a reference solution")


def agent_visible_context(task: GoldenTask) -> str:
    """The existing code the agents are shown: the seed files, and nothing else."""
    return "\n\n".join(f"# {path}\n{content}" for path, content in task.seed_files.items())
