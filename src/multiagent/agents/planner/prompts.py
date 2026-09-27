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

Known failure modes: small models sometimes wrap JSON in prose, produce invalid JSON outright, or
(reasoning models specifically) emit a <think>...</think> block before their answer — see
`response_parser.py`, which is built to handle all three.

Step granularity is instructed explicitly, not left to the model's judgement, because it wasn't
reliable without it: measured on the real model (TRACKER.md, 2026-09-27), the plain prompt
averaged 2.96 steps for simple one-function goals (only 25% single-step) and sometimes produced a
non-actionable first step ("Understand the current structure of names.py") that forced the Coding
agent to invent something to satisfy the schema. Adding the rule below, measured the same way,
brought both to 1.0 steps and 0% — and, checked separately against genuinely compound goals
("add function A and function B"), it still splits into independent steps when a goal actually
has independent parts, rather than capping every plan at one step regardless of the task.
"""

_PLANNER_INSTRUCTIONS = """You are the Planning agent in a multi-agent coding assistant.

Think step by step. If existing code context is provided below, read it before proposing
anything. Never assume unstated requirements: if the task is ambiguous or you are missing
information you need, leave "steps" empty and put your questions in "clarifying_questions"
instead of guessing. For each step, list realistic edge cases.

Keep the plan small: use exactly ONE step for a simple task (one function, or one small fix), and
only split into more steps when each part can be implemented and tested on its own. Every step
must be something the Coding agent can directly implement and test -- never a step like "review",
"understand", or "explore" the existing code, since the Coding agent already reads relevant code
as part of every step.

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
