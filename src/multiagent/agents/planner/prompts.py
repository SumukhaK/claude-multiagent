"""Prompt template for the Planning agent.

Purpose: turn a user's goal (plus any existing code the Planner has already read) into either a
step-by-step Plan or a request for clarification — never a guess at unstated requirements.

Input variables: `goal` (the task, required), `code_context` (existing code relevant to the
task, read via ReadOnlyFilesystem beforehand — omitted entirely when empty, since an empty
section would waste tokens out of an already-tight ~4096-token slot budget, see REQUIREMENTS.md
§6).

Expected output format: a single JSON object matching the `Plan` schema in
`multiagent/contracts/messages.py` — `{"kind": "plan", "goal": ..., "steps": [...],
"clarifying_questions": [...]}`. `steps` is left empty and `clarifying_questions` filled in when
the Planner needs more information rather than guessing.

Known failure modes: the local reasoning model (DeepSeek-R1-Distill) emits a
<think>...</think> block before its answer, and small models sometimes wrap JSON in prose or
produce invalid JSON outright — see `response_parser.py`, which is built specifically to handle
both.
"""

_PLANNER_INSTRUCTIONS = """You are the Planning agent in a multi-agent coding assistant.

Think step by step. If existing code context is provided below, read it before proposing
anything. Never assume unstated requirements: if the task is ambiguous or you are missing
information you need, leave "steps" empty and put your questions in "clarifying_questions"
instead of guessing. For each step, list realistic edge cases.

Respond with ONLY a single JSON object, no prose before or after it, matching exactly this
shape:
{"kind": "plan", "goal": "<restate the goal>", "steps": [{"step_id": 1, "description": "...", \
"edge_cases": ["..."]}], "clarifying_questions": []}"""


def render_planner_prompt(goal: str, code_context: str = "") -> str:
    """Build the full prompt for one Planner turn."""
    context_section = f"\n\nExisting code context:\n{code_context}" if code_context else ""
    return (
        f"{_PLANNER_INSTRUCTIONS}\n\n"
        f"Task: {goal}{context_section}\n\n"
        "Respond with the JSON object now."
    )
