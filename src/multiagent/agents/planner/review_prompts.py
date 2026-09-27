"""Prompt template for the Planning agent's step-review gate.

Purpose: after the Coding agent reports a completed step, ask the Planner whether the change
actually satisfies that step before the orchestrator advances — CLAUDE.md §4's mandatory review
gate. The test-passed/failed outcome is stated plainly rather than left for the model to infer.

Input variables: `step` (the PlanStep being reviewed), `report` (the Coder's CodeChangeReport,
including the files as written), `code_context` (optional, omitted when empty for the same
context-budget reason as every other prompt in this project — see REQUIREMENTS.md §6), `goal` (the
overall task).

What the reviewer is given, and why: the files themselves, the overall goal, and a rubric that
approves unless a concrete defect can be named. Measured on saved evaluation runs (failed_experiment.md
§8): a reviewer shown only file names and a one-line summary rejected correct work by deferring
("it is unclear whether the tests verify X, the review should confirm...") because it had nothing
to verify against, and judged the whole task against one narrow step ("Open calc.py").

Expected output format: a single JSON object matching the StepReview schema in
`multiagent/contracts/messages.py` — `{"kind": "step_review", "step_id": ..., "approved": bool,
"feedback": "..."}`.

Known failure modes: shared with every other prompt in this project (a reasoning model's <think>
block, malformed/truncated JSON — see review_parser.py). A passing test run doesn't guarantee the
test actually verifies the right thing (REQUIREMENTS.md §8), which is exactly why this review step
exists rather than trusting `tests_passed` alone.
"""

from multiagent.contracts.messages import CodeChangeReport, PlanStep
from multiagent.guardrails.input_filter import sanitize_tool_output

_REVIEW_INSTRUCTIONS = """You are the Planning agent, reviewing a completed step before the \
orchestrator moves on to the next one.

The test run in the report below is a real run: if it says the tests passed, they passed. The \
files are shown exactly as the Coding agent wrote them, so everything you need to judge the change \
is in front of you.

Approve when the code shown is a correct, reasonable contribution to the overall task and to this \
step. The step may be one narrow part of the task, and doing more of the task than the step names \
is fine. Reject only when you can point to a concrete defect in the code shown: wrong behaviour, a \
case the step names that is not handled, a test that asserts nothing, or code unrelated to the \
task. Do not reject because you cannot verify something: "the tests should cover X" is not a \
defect unless the tests shown really fail to. In your feedback, either name the specific defect and \
the fix the Coding agent should make, in one or two sentences, or say briefly why the change is \
fine.

Respond with ONLY a single JSON object, no prose before or after it, matching exactly this
shape:
{"kind": "step_review", "step_id": <int>, "approved": <true or false>, "feedback": "..."}"""


def render_review_prompt(
    step: PlanStep, report: CodeChangeReport, code_context: str = "", goal: str = ""
) -> str:
    """Build the full prompt for one step-review turn."""
    goal_section = f"Overall task: {goal}\n\n" if goal else ""
    edge_cases_section = (
        f"\nKnown edge cases to handle: {', '.join(step.edge_cases)}" if step.edge_cases else ""
    )
    context_section = f"\n\nExisting code context:\n{code_context}" if code_context else ""
    tests_status = "passed" if report.tests_passed else "failed"
    files_section = ""
    if report.file_contents:
        files = "\n\n".join(
            f"--- {path} ---\n{content}" for path, content in report.file_contents.items()
        )
        files_section = f"\n\nFiles as written:\n{sanitize_tool_output(files)}"
    return (
        f"{_REVIEW_INSTRUCTIONS}\n\n"
        f"{goal_section}"
        f"Step {step.step_id}: {step.description}{edge_cases_section}{context_section}\n\n"
        f"Coder's report — files changed: {', '.join(report.files_changed)}; "
        f"tests added: {', '.join(report.tests_added)}; tests {tests_status}; "
        f"summary: {report.summary}"
        f"{files_section}\n\n"
        "Respond with the JSON object now."
    )
