"""Prompt template for the Coding agent.

Purpose: turn one approved plan step (plus any existing code the Coder has already read) into a
TDD-ordered code change proposal — a failing test first, then the implementation, scoped to
exactly this one step.

Input variables: `step` (a PlanStep: step_id, description, edge_cases), `code_context` (existing
code relevant to this step — omitted entirely when empty, same context-budget reason as the
Planner's prompt, see REQUIREMENTS.md §6).

Expected output format: a single JSON object matching the CodeChangeProposal schema in
`multiagent/agents/coder/schemas.py` — `{"kind": "code_change", "step_id": ..., "test_files":
[{"path": ..., "content": ...}], "implementation_files": [...], "summary": ...}`. At least one
test file is required — the schema itself enforces this, not just the prompt wording.

Known failure modes: shared with the Planner (this model's <think> block, malformed/truncated
JSON — see response_parser.py). Coding responses also contain real file content rather than
short descriptions, so they're more likely to be truncated at a given max_tokens — see
agent.py's docstring for the measured implications.
"""

from multiagent.contracts.messages import PlanStep

_CODER_INSTRUCTIONS = """You are the Coding agent in a multi-agent coding assistant.

You are given exactly one step from an already-approved plan. If existing code context is
provided below, read it before writing anything -- a change must not break what already works.
Test-Driven Development is mandatory: propose a failing test first, then the implementation that
makes it pass. Keep the change minimal and scoped to this one step only.

Respond with ONLY a single JSON object, no prose before or after it, matching exactly this
shape:
{"kind": "code_change", "step_id": <int>, "test_files": [{"path": "...", "content": "..."}], \
"implementation_files": [{"path": "...", "content": "..."}], "summary": "..."}"""


def render_coder_prompt(step: PlanStep, code_context: str = "") -> str:
    """Build the full prompt for one Coder turn."""
    edge_cases_section = (
        f"\nKnown edge cases to handle: {', '.join(step.edge_cases)}" if step.edge_cases else ""
    )
    context_section = f"\n\nExisting code context:\n{code_context}" if code_context else ""
    return (
        f"{_CODER_INSTRUCTIONS}\n\n"
        f"Step {step.step_id}: {step.description}{edge_cases_section}{context_section}\n\n"
        "Respond with the JSON object now."
    )
