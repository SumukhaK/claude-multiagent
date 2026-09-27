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


def _report_with_code(**overrides):
    fields = dict(
        step_id=1,
        files_changed=["calc.py", "test_calc.py"],
        tests_added=["test_calc.py"],
        tests_passed=True,
        summary="added add()",
        file_contents={
            "calc.py": "def add(a, b):\n    return a + b\n",
            "test_calc.py": "def test_add():\n    assert add(1, 2) == 3\n",
        },
    )
    fields.update(overrides)
    return CodeChangeReport(**fields)


def test_the_review_prompt_shows_the_code_that_was_written_wrapped_as_data():
    """Measured: a reviewer that could not see the code rejected correct work 'because it is unclear
    whether the tests verify X', so it is given the files themselves."""
    prompt = render_review_prompt(step=PlanStep(step_id=1, description="add add()"), report=_report_with_code())

    assert "def add(a, b):" in prompt and "assert add(1, 2) == 3" in prompt
    assert "calc.py" in prompt
    assert "<tool_output>" in prompt  # code is data, never instructions


def test_the_review_prompt_shows_the_overall_goal_next_to_the_step():
    prompt = render_review_prompt(
        step=PlanStep(step_id=1, description="Open calc.py"), report=_report_with_code(), goal="Add add(a, b) in calc.py"
    )

    assert "Overall task" in prompt and "Add add(a, b) in calc.py" in prompt


def test_the_rubric_approves_unless_a_concrete_defect_can_be_named():
    prompt = " ".join(render_review_prompt(step=PlanStep(step_id=1, description="x"), report=_report_with_code()).split())

    assert "concrete defect" in prompt
    assert "doing more of the task than the step names is fine" in prompt
    assert "cannot verify" in prompt  # an inability to verify is not a reason to reject


def test_a_report_without_file_contents_still_renders_with_no_code_section():
    prompt = render_review_prompt(step=PlanStep(step_id=1, description="x"), report=_report_with_code(file_contents={}))

    assert "<tool_output>" not in prompt
