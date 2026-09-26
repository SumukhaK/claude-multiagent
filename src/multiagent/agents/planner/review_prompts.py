"""Prompt template for the Planning agent's step-review gate.

Purpose: after the Coding agent reports a completed step, ask the Planner whether the change
actually satisfies that step before the orchestrator advances — CLAUDE.md §4's mandatory review
gate. The test-passed/failed outcome is stated plainly rather than left for the model to infer.

Input variables: `step` (the PlanStep being reviewed), `report` (the Coder's CodeChangeReport),
`code_context` (optional, omitted when empty for the same context-budget reason as every other
prompt in this project — see REQUIREMENTS.md §6).

Expected output format: a single JSON object matching the StepReview schema in
`multiagent/contracts/messages.py` — `{"kind": "step_review", "step_id": ..., "approved": bool,
"feedback": "..."}`.

Known failure modes: shared with every other prompt in this project (this model's <think>
block, malformed/truncated JSON — see review_parser.py). A passing test run doesn't guarantee
the test actually verifies the right thing (REQUIREMENTS.md §8), which is exactly why this
review step exists rather than trusting `tests_passed` alone.
"""

from multiagent.contracts.messages import CodeChangeReport, PlanStep

_REVIEW_INSTRUCTIONS = """You are the Planning agent, reviewing a completed step before the \
orchestrator moves on to the next one.

A test run passing does not guarantee the test actually verifies the right thing — check whether
the files changed and the summary genuinely address the step's description and edge cases, not
just whether tests_passed is true.

Respond with ONLY a single JSON object, no prose before or after it, matching exactly this
shape:
{"kind": "step_review", "step_id": <int>, "approved": <true or false>, "feedback": "..."}"""


def render_review_prompt(step: PlanStep, report: CodeChangeReport, code_context: str = "") -> str:
    """Build the full prompt for one step-review turn."""
    edge_cases_section = (
        f"\nKnown edge cases to handle: {', '.join(step.edge_cases)}" if step.edge_cases else ""
    )
    context_section = f"\n\nExisting code context:\n{code_context}" if code_context else ""
    tests_status = "passed" if report.tests_passed else "failed"
    return (
        f"{_REVIEW_INSTRUCTIONS}\n\n"
        f"Step {step.step_id}: {step.description}{edge_cases_section}{context_section}\n\n"
        f"Coder's report — files changed: {', '.join(report.files_changed)}; "
        f"tests added: {', '.join(report.tests_added)}; tests {tests_status}; "
        f"summary: {report.summary}\n\n"
        "Respond with the JSON object now."
    )
