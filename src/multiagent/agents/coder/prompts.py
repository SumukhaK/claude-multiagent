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

When decoding is constrained the format is described in words, deliberately: showing a
`"content": "..."` shape made the model return "..." as file bodies, and a worked example was
copied verbatim (17 of 24 samples). Unconstrained, the explicit shape is kept, because without it
the model invented its own JSON structure. See REQUIREMENTS.md §11.5-11.6.

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

"""

# Unconstrained: the model has nothing but the prompt to tell it the JSON shape.
_FORMAT_SHAPE = """Respond with ONLY a single JSON object, no prose before or after it, matching exactly this
shape:
{"kind": "code_change", "step_id": <int>, "test_files": [{"path": "...", "content": "..."}], \
"implementation_files": [{"path": "...", "content": "..."}], "summary": "..."}"""

# Constrained: the grammar supplies the shape, so the prompt states the rules in words. Showing a
# `"content": "..."` shape here made the model return "..." as file bodies.
_FORMAT_WORDS = """Reply with ONE JSON object and nothing else. Its keys are: kind (always "code_change"), step_id
(the step number below), test_files, implementation_files and summary (one sentence). Each entry
of test_files and implementation_files is an object with a relative "path" and the complete
"content" of that file.

Rules:
- test_files holds the pytest test file. Its name starts with test_ and it defines at least one
  function named test_something that uses assert.
- implementation_files holds the code being tested, in a normal module name. If the step names a
  file, use that name.
- Paths are short relative names like numbers.py, never absolute, never a directory.
- Write real code and real tests, never placeholders."""


_MAX_FEEDBACK_CHARS = 800


def render_coder_prompt(
    step: PlanStep,
    code_context: str = "",
    constrained: bool = False,
    goal: str = "",
    feedback: str = "",
) -> str:
    """Build the full prompt for one Coder turn. `constrained` says the response will be decoded
    against the proposal's JSON schema, which selects the words-only format description. `goal` is
    the overall task: a step often drops details it carries, such as a file name. `feedback` is the
    reviewer's reason for rejecting the previous attempt, so a retry is informed, not a re-roll."""
    edge_cases_section = (
        f"\nKnown edge cases to handle: {', '.join(step.edge_cases)}" if step.edge_cases else ""
    )
    context_section = f"\n\nExisting code context:\n{code_context}" if code_context else ""
    format_section = _FORMAT_WORDS if constrained else _FORMAT_SHAPE
    goal_section = (
        f"Overall task (if it names a file, use that file name): {goal}\n\n" if goal else ""
    )
    feedback_section = (
        f"\n\nA reviewer rejected your previous attempt at this step. Fix what it names:\n"
        f"{feedback[:_MAX_FEEDBACK_CHARS]}"
        if feedback
        else ""
    )
    return (
        f"{_CODER_INSTRUCTIONS}\n\n{format_section}\n\n{goal_section}"
        f"Step {step.step_id}: {step.description}{edge_cases_section}{context_section}"
        f"{feedback_section}\n\n"
        "Respond with the JSON object now."
    )
