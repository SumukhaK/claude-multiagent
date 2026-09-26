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
