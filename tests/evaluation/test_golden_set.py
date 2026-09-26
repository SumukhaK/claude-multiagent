"""Validity tests for the golden task set.

Every metric in the evaluation rests on these tasks, so they are tested as rigorously as code: a
hidden acceptance test that passes on an empty repo, or fails on a correct solution, would make
the whole report meaningless. Nothing here calls an LLM.
"""

import pytest

from multiagent.evaluation.golden import agent_visible_context
from multiagent.evaluation.golden_tasks import GOLDEN_TASKS
from multiagent.guardrails.input_filter import check_user_input
from multiagent.tools.pytest_runner import SandboxedPytestRunner

IMPLEMENT_TASKS = [task for task in GOLDEN_TASKS if task.expectation == "implement"]
REFUSE_TASKS = [task for task in GOLDEN_TASKS if task.expectation == "refuse"]


def _sandbox_with(tmp_path, *file_sets):
    for files in file_sets:
        for path, content in files.items():
            (tmp_path / path).write_text(content, encoding="utf-8")
    return SandboxedPytestRunner(tmp_path, timeout_seconds=30)


def test_the_set_is_non_trivial_and_ids_are_unique():
    ids = [task.id for task in GOLDEN_TASKS]

    assert len(ids) == len(set(ids))
    assert len(IMPLEMENT_TASKS) >= 8
    assert len(REFUSE_TASKS) >= 2


def test_the_set_covers_every_category():
    assert {task.category for task in GOLDEN_TASKS} == {"feature", "bugfix", "clarification", "adversarial"}


@pytest.mark.parametrize("task", IMPLEMENT_TASKS, ids=lambda t: t.id)
def test_the_acceptance_test_passes_on_the_reference_solution(task, tmp_path):
    runner = _sandbox_with(tmp_path, task.seed_files, task.reference_solution, {"test_acceptance.py": task.acceptance_test})

    result = runner.run(targets=["test_acceptance.py"])

    assert result.passed, result.output


@pytest.mark.parametrize("task", IMPLEMENT_TASKS, ids=lambda t: t.id)
def test_the_acceptance_test_fails_without_the_solution(task, tmp_path):
    """Bug-fix tasks fail on the buggy seed; feature tasks fail on an empty repo. Either way, an
    agent that does nothing must not score a success."""
    runner = _sandbox_with(tmp_path, task.seed_files, {"test_acceptance.py": task.acceptance_test})

    result = runner.run(targets=["test_acceptance.py"])

    assert not result.passed


@pytest.mark.parametrize("task", IMPLEMENT_TASKS, ids=lambda t: t.id)
def test_the_acceptance_test_is_hidden_from_the_agents(task):
    visible = task.goal + agent_visible_context(task)

    assert task.acceptance_test.strip() not in visible
    assert "acceptance" not in visible.lower()


@pytest.mark.parametrize("task", IMPLEMENT_TASKS, ids=lambda t: t.id)
def test_ordinary_implementation_goals_are_not_refused_by_the_input_guardrail(task):
    """If the guardrail refused a legitimate golden task, the evaluation would be measuring the
    filter's false positives rather than the agents."""
    assert check_user_input(task.goal).allowed is True


@pytest.mark.parametrize("task", REFUSE_TASKS, ids=lambda t: t.id)
def test_adversarial_goals_are_refused_by_the_input_guardrail(task):
    assert check_user_input(task.goal).allowed is False


def test_bugfix_tasks_show_the_agents_the_buggy_code():
    for task in (t for t in IMPLEMENT_TASKS if t.category == "bugfix"):
        assert task.seed_files, task.id
        for content in task.seed_files.values():
            assert content.strip() in agent_visible_context(task)


def test_clarification_tasks_supply_an_answer_to_give_when_asked():
    for task in (t for t in GOLDEN_TASKS if t.category == "clarification"):
        assert task.clarification_answer
