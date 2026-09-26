"""Tests for the Planning agent's step-review prompt template."""

from multiagent.agents.planner.review_prompts import render_review_prompt
from multiagent.contracts.messages import CodeChangeReport, PlanStep


def _report(tests_passed: bool) -> CodeChangeReport:
    return CodeChangeReport(
        step_id=1,
        files_changed=["calc.py", "test_calc.py"],
        tests_added=["test_calc.py"],
        tests_passed=tests_passed,
        summary="added add()",
    )


def test_prompt_includes_the_step_description_and_summary():
    step = PlanStep(step_id=1, description="add add()")
    prompt = render_review_prompt(step=step, report=_report(True))

    assert "add add()" in prompt
    assert "added add()" in prompt


def test_prompt_states_whether_tests_passed():
    step = PlanStep(step_id=1, description="add add()")

    passed_prompt = render_review_prompt(step=step, report=_report(True))
    failed_prompt = render_review_prompt(step=step, report=_report(False))

    assert "passed" in passed_prompt.lower()
    assert "failed" in failed_prompt.lower()


def test_prompt_lists_the_changed_and_test_files():
    step = PlanStep(step_id=1, description="add add()")
    prompt = render_review_prompt(step=step, report=_report(True))

    assert "calc.py" in prompt
    assert "test_calc.py" in prompt


def test_prompt_instructs_json_output_with_approved_and_feedback():
    step = PlanStep(step_id=1, description="add add()")
    prompt = render_review_prompt(step=step, report=_report(True))

    assert "approved" in prompt
    assert "feedback" in prompt
