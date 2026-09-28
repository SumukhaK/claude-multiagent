"""Tests for the Planning agent's prompt template.

Per REQUIREMENTS.md §1: the Planner must read existing code before planning, ask clarifying
questions instead of assuming, and enumerate edge cases — the prompt is what actually instructs
the model to do that, so it's worth testing directly rather than trusting it by inspection.
"""

from multiagent.agents.planner.prompts import render_planner_prompt


def test_prompt_includes_the_goal():
    prompt = render_planner_prompt(goal="add a health check endpoint")

    assert "add a health check endpoint" in prompt


def test_prompt_includes_code_context_when_provided():
    prompt = render_planner_prompt(goal="fix the bug", code_context="def broken(): pass")

    assert "def broken(): pass" in prompt


def test_prompt_omits_the_code_context_section_when_none_given():
    """An empty section would waste tokens out of an already-tight ~4096-token slot budget."""
    prompt = render_planner_prompt(goal="fix the bug", code_context="")

    assert "Existing code context" not in prompt


def test_prompt_instructs_the_model_to_respond_with_json_only():
    prompt = render_planner_prompt(goal="fix the bug")

    assert "JSON" in prompt


def test_prompt_instructs_the_model_to_ask_instead_of_assume():
    prompt = render_planner_prompt(goal="fix the bug")

    assert "clarifying_questions" in prompt


def test_prompt_tells_the_model_to_keep_simple_tasks_to_one_step():
    """Measured live (TRACKER.md, 2026-09-27): the existing prompt averaged 2.96 steps/plan with
    only 25% single-step, and produced non-actionable steps ("Understand the current structure
    ..."). Adding this instruction, measured the same way, dropped both to 1.0 steps and 0%."""
    prompt = render_planner_prompt(goal="fix the bug").lower()

    assert "one step" in prompt
    assert "understand" in prompt and "review" in prompt and "explore" in prompt


def test_prompt_still_allows_splitting_a_task_that_has_independent_parts():
    """The instruction is advisory ('only split when...'), not a hard one-step cap -- verified
    live against the real model on genuinely compound goals before this was written."""
    prompt = render_planner_prompt(goal="fix the bug").lower()

    assert "only split" in prompt or "split into more steps" in prompt


def test_prompt_gives_concrete_criteria_for_when_a_goal_is_ambiguous():
    """Measured live (TRACKER.md, 2026-09-27): the prompt already said 'ask instead of guessing',
    but the model asked 0 of 15 times on genuinely ambiguous goals regardless -- prose alone
    wasn't enough. Concrete criteria (no example input/output, no stated input type), measured the
    same way, raised that to 6 of 18 while still asking 0 of 18 times on clear-cut goals -- a real
    but partial improvement, not a full fix (rate varies a lot by exact wording)."""
    prompt = render_planner_prompt(goal="fix the bug").lower()

    assert "concrete example" in prompt or "example input" in prompt
    assert "input type" in prompt or "type or shape" in prompt


def test_prompt_shows_a_worked_example_of_the_ask_shape():
    """The model pattern-matches to whatever JSON shape is shown worked, not just to prose (the
    same lesson as the granularity fix) -- so the ask path needs its own example, not just the
    one steps-filled-in example the prompt already had."""
    prompt = render_planner_prompt(goal="fix the bug")

    assert '"steps": [], "clarifying_questions": ["<question>"]}' in prompt


def test_prompt_tells_the_model_to_state_edge_case_behavior_definitely_not_as_a_hint():
    """Measured live (TRACKER.md, 2026-09-27): a hedged edge case ("may raise a TypeError")
    produced a real coder test that contradicted itself for similar invalid inputs. This
    instruction, measured the same way, produced 0 of 18 hedged edge cases (vs. an unmeasured
    baseline that included at least one real hedge)."""
    prompt = render_planner_prompt(goal="fix the bug").lower()

    assert "definitely" in prompt
    assert "hint" in prompt or "possibility" in prompt


def test_prompt_forbids_a_step_that_only_adds_more_tests():
    """Found live: a redundant second step ("Add a test case for each of the edge cases in the
    function") that isn't actionable and isn't needed under TDD, and slipped past the existing
    review/understand/explore rule because it isn't worded like one of those. Measured fix: 0 of 8
    on the exact goal that had produced it live."""
    prompt = render_planner_prompt(goal="fix the bug").lower()

    assert "adds more tests" in prompt or "only adds" in prompt


def test_prompt_shows_a_decomposition_ambiguity_example_that_is_not_the_golden_task_itself():
    """Measured live (TRACKER.md, 2026-09-28): 'format a person's name' asked 0 of 6 in every
    measurement even under the general ambiguity criteria -- a name reads as too obviously a
    single string. A concrete worked example of the same *kind* of ambiguity (one field that
    could be one value or split into parts), using a different field so the model has to
    transfer the pattern rather than match a memorized case, raised that specific wording to 3
    of 6. The example must not be the eval's own golden task, or this would just be an answer key."""
    prompt = render_planner_prompt(goal="fix the bug").lower()

    assert "split into separate parts" in prompt or "separate street" in prompt
    assert "person's name" not in prompt
