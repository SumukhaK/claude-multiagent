"""Tests for the Coding agent's prompt template."""

from multiagent.agents.coder.prompts import render_coder_prompt
from multiagent.contracts.messages import PlanStep


def test_prompt_includes_the_step_id_and_description():
    step = PlanStep(step_id=1, description="add a health endpoint")

    prompt = render_coder_prompt(step=step)

    assert "Step 1" in prompt
    assert "add a health endpoint" in prompt


def test_prompt_includes_edge_cases_when_present():
    step = PlanStep(step_id=1, description="add a health endpoint", edge_cases=["empty body"])

    prompt = render_coder_prompt(step=step)

    assert "empty body" in prompt


def test_prompt_omits_edge_cases_section_when_none_given():
    step = PlanStep(step_id=1, description="add a health endpoint")

    prompt = render_coder_prompt(step=step)

    assert "edge cases" not in prompt.lower()


def test_prompt_includes_code_context_when_provided():
    step = PlanStep(step_id=1, description="fix the bug")

    prompt = render_coder_prompt(step=step, code_context="def broken(): pass")

    assert "def broken(): pass" in prompt


def test_prompt_omits_the_code_context_section_when_none_given():
    step = PlanStep(step_id=1, description="fix the bug")

    prompt = render_coder_prompt(step=step, code_context="")

    assert "Existing code context" not in prompt


def test_prompt_mandates_tdd_and_json_output():
    step = PlanStep(step_id=1, description="fix the bug")

    prompt = render_coder_prompt(step=step)

    assert "mandatory" in prompt.lower()
    assert "test_files" in prompt
