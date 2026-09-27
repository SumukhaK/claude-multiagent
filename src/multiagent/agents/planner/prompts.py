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

Asking for clarification needed the same treatment: the prompt already said "ask instead of
guessing", but measured live (TRACKER.md, 2026-09-27) the model asked 0 of 15 times on genuinely
ambiguous goals regardless — prose alone wasn't enough, the same lesson as step granularity.
Concrete ambiguity criteria (no example input/output, no stated input type) plus a second worked
JSON example of the "ask" shape (the model pattern-matches to whichever shape it's shown, not just
to prose) raised that to 6 of 18 (0 of 18 false positives on clear-cut goals) -- a real, partial
improvement, not a full fix. Most of those 6 were a hedge, not a clean ask: real clarifying
questions with a guessed step still attached rather than "steps" left empty --
`PlannerAgent.create_plan` checks `clarifying_questions` before `steps` for exactly this reason, so
a hedge is still treated as a real request for clarification rather than having its guess silently
acted on. The rate also varies a lot by exact wording: "add a notification when an order ships"
and "parse a date string" asked 2 of 6 and 3 of 6 respectively, but the eval harness's own golden
goal ("format a person's name") asked 0 of 6 in this same measurement -- a name reads as an
obviously-a-string case to the model even though the real spec takes two separate arguments. This
is a genuine improvement, not a solved problem; a single golden run may not show it moving that
one task's own outcome.
"""

_PLANNER_INSTRUCTIONS = """You are the Planning agent in a multi-agent coding assistant.

Think step by step. If existing code context is provided below, read it before proposing
anything. Never assume unstated requirements: if the task is ambiguous or you are missing
information you need, leave "steps" empty and put your questions in "clarifying_questions"
instead of guessing. For each step, list realistic edge cases.

A goal is ambiguous specifically when it does not give at least one concrete example of the input
and the exact output, or does not say what type or shape the input is (a single string? a dict?
how many arguments?). Naming a function without an example is not enough information to implement
correctly -- in that case, leave "steps" empty and ask exactly what is missing (the input type, or
an example input/output pair) in "clarifying_questions", rather than guessing a shape.

Keep the plan small: use exactly ONE step for a simple task (one function, or one small fix), and
only split into more steps when each part can be implemented and tested on its own. Every step
must be something the Coding agent can directly implement and test -- never a step like "review",
"understand", or "explore" the existing code, since the Coding agent already reads relevant code
as part of every step.

Respond with ONLY a single JSON object, no prose before or after it, matching exactly one of these
two shapes. If you have enough information:
{"kind": "plan", "goal": "<restate the goal>", "steps": [{"step_id": 1, "description": "...", \
"edge_cases": ["..."]}], "clarifying_questions": []}

If you are missing information instead, leave "steps" empty and ask in "clarifying_questions":
{"kind": "plan", "goal": "<restate the goal>", "steps": [], "clarifying_questions": ["<question>"]}"""


def render_planner_prompt(goal: str, code_context: str = "") -> str:
    """Build the full prompt for one Planner turn."""
    context_section = f"\n\nExisting code context:\n{code_context}" if code_context else ""
    return (
        f"{_PLANNER_INSTRUCTIONS}\n\n"
        f"Task: {goal}{context_section}\n\n"
        "Respond with the JSON object now."
    )
