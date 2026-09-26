"""Tests for aggregating run results into the published report."""

import pytest

from multiagent.evaluation.report import (
    aggregate,
    load_results,
    render_markdown,
    save_results,
    update_readme,
)
from multiagent.evaluation.runner import RunResult


def result(**overrides):
    params = {
        "task_id": "t", "category": "feature", "expectation": "implement", "repeat": 0,
        "outcome": "success", "orchestrator_status": "done", "acceptance_passed": True,
        "asked_for_clarification": False, "fake_test": False, "had_failure_event": False,
        "wall_seconds": 10.0, "total_tokens": 1000, "llm_seconds": 5.0,
        "llm_latencies": {"planner": [1.0, 3.0], "coder": [2.0]},
        "tool_operations": [], "coder_test_files": 1, "error": None,
    }
    params.update(overrides)
    return RunResult(**params)


def test_success_and_false_success_rates_use_all_implementation_runs():
    runs = [result(), result(), result(outcome="false_success", acceptance_passed=False), result(outcome="escalated", orchestrator_status="failed", acceptance_passed=None)]

    report = aggregate(runs)

    assert report["implement_runs"] == 4
    assert report["success"] == (2, 4)
    assert report["false_success"] == (1, 4)
    assert report["false_success_of_done"] == (1, 3)  # of the 3 runs that claimed done, 1 was wrong


def test_recovery_is_counted_only_among_runs_that_hit_a_failure():
    runs = [
        result(had_failure_event=True),  # failed once, recovered
        result(had_failure_event=True, outcome="escalated", orchestrator_status="failed", acceptance_passed=None),
        result(),  # never failed: not part of the recovery denominator
    ]

    assert aggregate(runs)["recovery"] == (1, 2)


def test_fake_test_rate_only_counts_runs_where_the_coder_wrote_a_test_file():
    runs = [result(fake_test=True), result(fake_test=False), result(coder_test_files=0)]

    assert aggregate(runs)["fake_test"] == (1, 2)


def test_tool_success_is_per_operation_and_excludes_the_stubbed_pull_request():
    runs = [result(tool_operations=[("create_branch", True), ("commit", True), ("push", False), ("create_pull_request", True)])]

    tool = aggregate(runs)["tool_success"]

    assert tool == {"create_branch": (1, 1), "commit": (1, 1), "push": (0, 1)}


def test_guardrail_correctness_covers_both_directions():
    runs = [
        result(expectation="refuse", category="adversarial", outcome="correctly_refused", orchestrator_status="refused", acceptance_passed=None),
        result(expectation="refuse", category="adversarial", outcome="not_refused", orchestrator_status="done", acceptance_passed=None),
        result(outcome="wrongly_refused", orchestrator_status="refused", acceptance_passed=None),
        result(),
    ]

    report = aggregate(runs)

    assert report["adversarial_refused"] == (1, 2)
    assert report["benign_not_refused"] == (1, 2)


def test_clarification_asked_counts_only_clarification_tasks():
    runs = [result(category="clarification", asked_for_clarification=True), result(category="clarification"), result(asked_for_clarification=True)]

    assert aggregate(runs)["clarification_asked"] == (1, 2)


def test_latency_percentiles_are_pooled_per_role_and_per_task():
    runs = [result(wall_seconds=10.0), result(wall_seconds=30.0)]

    report = aggregate(runs)

    assert report["llm_latency"]["planner"]["p50"] == pytest.approx(2.0)
    assert report["task_wall_seconds"]["p50"] == pytest.approx(20.0)


def test_cost_is_tokens_and_marginal_dollars_are_zero_for_local_inference():
    report = aggregate([result(total_tokens=1000, llm_seconds=5.0), result(total_tokens=3000, llm_seconds=15.0)])

    assert report["tokens"]["total"] == 4000
    assert report["tokens"]["mean_per_run"] == 2000
    assert report["llm_seconds_total"] == 20.0


def test_a_run_with_no_data_yields_none_not_a_crash():
    report = aggregate([])

    assert report["success"] == (0, 0)
    assert report["task_wall_seconds"]["p50"] is None


def test_markdown_reports_rates_with_intervals_and_warns_about_small_samples():
    runs = [result() for _ in range(3)] + [result(outcome="escalated", orchestrator_status="failed", acceptance_passed=None)]

    markdown = render_markdown(aggregate(runs), metadata={"model": "test-model", "repeats": 2, "date": "2026-01-01"})

    assert "3/4" in markdown
    assert "95% CI" in markdown
    assert "test-model" in markdown
    assert "small sample" in markdown.lower()


def test_markdown_shows_a_per_task_breakdown():
    runs = [result(task_id="alpha"), result(task_id="alpha", outcome="escalated", orchestrator_status="failed", acceptance_passed=None), result(task_id="beta")]

    markdown = render_markdown(aggregate(runs), metadata={"model": "m", "repeats": 1, "date": "d"})

    assert "alpha" in markdown
    assert "beta" in markdown


def test_results_round_trip_through_json_lines(tmp_path):
    runs = [result(tool_operations=[("commit", True)]), result(task_id="other", error="x")]
    path = tmp_path / "runs.jsonl"

    save_results(runs, path)

    assert load_results(path) == runs


def test_update_readme_replaces_an_existing_marked_section_and_keeps_the_rest():
    readme = "# Title\n\nintro\n\n<!-- EVAL-RESULTS:START -->\nold numbers\n<!-- EVAL-RESULTS:END -->\n\nfooter\n"

    updated = update_readme(readme, "NEW SECTION")

    assert "NEW SECTION" in updated
    assert "old numbers" not in updated
    assert updated.startswith("# Title\n\nintro")
    assert updated.rstrip().endswith("footer")


def test_update_readme_appends_a_marked_section_when_none_exists():
    updated = update_readme("# Title\n\nintro\n", "NEW SECTION")

    assert updated.count("<!-- EVAL-RESULTS:START -->") == 1
    assert "NEW SECTION" in updated
    assert update_readme(updated, "NEWER").count("<!-- EVAL-RESULTS:START -->") == 1
