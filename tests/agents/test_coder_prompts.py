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


def test_prompt_has_no_dots_placeholder_shape_because_the_model_copies_it_literally():
    """Measured: shown `"content": "..."` the model returned "..." as the file body (constrained
    decoding lets any string through), so the format is described in words instead."""
    prompt = render_coder_prompt(step=PlanStep(step_id=1, description="add add()"), constrained=True)

    assert '"..."' not in prompt
    assert "..." not in prompt


def test_prompt_tells_the_model_to_use_relative_file_paths_never_placeholders():
    prompt = " ".join(render_coder_prompt(step=PlanStep(step_id=1, description="x"), constrained=True).lower().split())

    assert "relative" in prompt
    assert "never absolute" in prompt
    assert "never a directory" in prompt
    assert "never placeholders" in prompt


def test_prompt_separates_test_files_from_implementation_files_and_demands_a_test_function():
    prompt = " ".join(render_coder_prompt(step=PlanStep(step_id=1, description="x"), constrained=True).split())

    assert "test_files holds the pytest test file" in prompt
    assert "implementation_files holds the code being tested" in prompt
    assert "at least one function named test_" in prompt
    assert "assert" in prompt


def test_prompt_contains_no_worked_example_the_model_could_copy():
    """A worked example was tried and copied verbatim in 17 of 24 samples."""
    prompt = render_coder_prompt(step=PlanStep(step_id=1, description="add add()"), constrained=True)

    assert "shout" not in prompt
    assert '"kind": "code_change"' not in prompt


def test_the_unconstrained_prompt_keeps_the_explicit_json_shape():
    """Without a grammar the model has nothing else to tell it the shape: measured, the words-only
    prompt made an unconstrained model invent its own JSON structure (10 of 16 failures in one run)."""
    prompt = render_coder_prompt(step=PlanStep(step_id=1, description="x"))

    assert '"test_files": [{"path"' in prompt


def test_the_constrained_prompt_describes_the_format_in_words_only():
    prompt = render_coder_prompt(step=PlanStep(step_id=1, description="x"), constrained=True)

    assert '"test_files": [{"path"' not in prompt
    assert "..." not in prompt
    assert "test_files holds the pytest test file" in prompt


def test_the_prompt_shows_the_overall_goal_and_says_to_use_a_file_name_it_mentions():
    for constrained in (False, True):
        prompt = " ".join(
            render_coder_prompt(
                step=PlanStep(step_id=1, description="Define add"),
                goal="Add add(a, b) in calc.py",
                constrained=constrained,
            ).split()
        )

        assert "Overall task" in prompt
        assert "Add add(a, b) in calc.py" in prompt
        assert "use that file name" in prompt


def test_the_prompt_has_no_goal_section_when_no_goal_is_given():
    prompt = render_coder_prompt(step=PlanStep(step_id=1, description="Define add"))

    assert "Overall task" not in prompt


def test_feedback_from_a_failed_attempt_is_shown_in_both_prompt_modes_and_absent_when_empty():
    step = PlanStep(step_id=1, description="add add()")
    for constrained in (False, True):
        with_feedback = render_coder_prompt(step=step, constrained=constrained, feedback="Handle b == 0.")
        without = render_coder_prompt(step=step, constrained=constrained)

        assert "Handle b == 0." in with_feedback
        assert "did not work" in with_feedback.lower()
        assert "did not work" not in without.lower()
