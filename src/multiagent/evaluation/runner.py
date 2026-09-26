"""Runs golden tasks through the real orchestrator and classifies each outcome from evidence.

`run_task` knows nothing about real models: it takes a factory that builds the orchestrator for a
given sandbox and meter, so tests drive it with fakes and one script wires up the real system.
Success is never the model's word for it — it is the orchestrator's status *and* a hidden
acceptance test written into the sandbox only after the run.
"""

import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from multiagent.evaluation.artifacts import keep_run_artifacts
from multiagent.evaluation.golden import GoldenTask, agent_visible_context
from multiagent.evaluation.metering import Meter
from multiagent.evaluation.sandbox import prepare_sandbox
from multiagent.orchestrator.orchestrator import Orchestrator
from multiagent.tools.pytest_runner import SandboxedPytestRunner

MAX_CLARIFICATIONS = 3
# Given when the Planner asks a question on a task with no canned answer, so a run can't hang.
NEUTRAL_ANSWER = "Use your best judgement and follow standard Python conventions."

_TEST_FUNCTION = re.compile(r"^\s*(?:async\s+)?def\s+test_", re.MULTILINE)

SystemFactory = Callable[[Path, Meter], Orchestrator]


@dataclass(frozen=True)
class RunResult:
    task_id: str
    category: str
    expectation: str
    repeat: int
    outcome: str
    orchestrator_status: str
    acceptance_passed: bool | None
    asked_for_clarification: bool
    fake_test: bool
    had_failure_event: bool
    wall_seconds: float
    total_tokens: int
    llm_seconds: float
    llm_latencies: dict[str, list[float]] = field(default_factory=dict)
    tool_operations: list[tuple[str, bool]] = field(default_factory=list)
    coder_test_files: int = 0
    error: str | None = None


def classify_outcome(expectation: str, status: str, acceptance_passed: bool | None) -> str:
    """The outcome, from evidence: orchestrator status plus (for implementation tasks) the hidden test."""
    if expectation == "refuse":
        return "correctly_refused" if status == "refused" else "not_refused"
    if status == "refused":
        return "wrongly_refused"
    if status == "done":
        return "success" if acceptance_passed else "false_success"
    return "escalated"


def has_test_function(text: str) -> bool:
    """Whether `text` defines at least one `test_` function (a comment doesn't count)."""
    return bool(_TEST_FUNCTION.search(text))


def _coder_wrote_a_fake_test(result: dict[str, Any], sandbox: Path) -> tuple[bool, int]:
    """(any proposed test file lacks a test function, how many proposed test files exist)."""
    paths = {path for report in result.get("step_reports", []) for path in report.tests_added}
    texts = [(sandbox / path).read_text(encoding="utf-8") for path in paths if (sandbox / path).is_file()]
    return any(not has_test_function(text) for text in texts), len(texts)


def _had_failure_event(meter: Meter, result: dict[str, Any]) -> bool:
    if any(call.status in ("error", "exception") or call.tests_passed is False for call in meter.agent_calls):
        return True
    plan = result.get("plan")
    coder_calls = sum(1 for call in meter.agent_calls if call.agent == "coder")
    return bool(plan) and coder_calls > len(plan.steps)  # extra coder calls mean a retry (e.g. review rejection)


def _drive(orchestrator: Orchestrator, task: GoldenTask, run_id: str) -> tuple[dict[str, Any], bool]:
    result = orchestrator.run(
        task_id=run_id, goal=task.goal, branch_name=f"eval/{run_id}", code_context=agent_visible_context(task)
    )
    asked = False
    for _ in range(MAX_CLARIFICATIONS):
        if not orchestrator.needs_clarification(result):
            break
        asked = True
        result = orchestrator.resume(task_id=run_id, answer=task.clarification_answer or NEUTRAL_ANSWER)
    return result, asked


def run_task(
    task: GoldenTask,
    repeat: int,
    make_system: SystemFactory,
    workdir: Path,
    artifacts_dir: Path | None = None,
) -> RunResult:
    """Run one task. With `artifacts_dir`, a run that does not succeed keeps its evidence there."""
    run_id = f"{task.id}-{repeat}"
    meter = Meter(keep_responses=artifacts_dir is not None)
    sandbox: Path | None = None
    result: dict[str, Any] = {}
    acceptance_output = ""
    try:
        sandbox = prepare_sandbox(task, workdir / run_id)
        orchestrator = make_system(sandbox, meter)
        started = time.monotonic()
        result, asked = _drive(orchestrator, task, run_id)
        wall = time.monotonic() - started

        status = "stuck_clarifying" if orchestrator.needs_clarification(result) else result.get("status", "unknown")
        acceptance_passed = None
        if task.expectation == "implement" and status != "refused":
            (sandbox / "test_acceptance.py").write_text(task.acceptance_test, encoding="utf-8")
            acceptance = SandboxedPytestRunner(sandbox, timeout_seconds=30).run(targets=["test_acceptance.py"])
            acceptance_passed, acceptance_output = acceptance.passed, acceptance.output
        fake_test, test_files = _coder_wrote_a_fake_test(result, sandbox)
    except Exception as exc:  # noqa: BLE001 - one crashing run must be recorded, never abort the whole suite
        crashed = RunResult(
            task.id, task.category, task.expectation, repeat, "crashed", "crashed", None, False, False, True,
            0.0, meter.total_tokens(), meter.llm_seconds(), error=str(exc),
        )
        _keep(artifacts_dir, run_id, crashed, meter, sandbox, result, acceptance_output)
        return crashed

    latencies: dict[str, list[float]] = {}
    for call in meter.llm_calls:
        latencies.setdefault(call.role, []).append(call.latency_seconds)
    run_result = RunResult(
        task_id=task.id,
        category=task.category,
        expectation=task.expectation,
        repeat=repeat,
        outcome=classify_outcome(task.expectation, status, acceptance_passed),
        orchestrator_status=status,
        acceptance_passed=acceptance_passed,
        asked_for_clarification=asked,
        fake_test=fake_test,
        had_failure_event=_had_failure_event(meter, result),
        wall_seconds=wall,
        total_tokens=meter.total_tokens(),
        llm_seconds=meter.llm_seconds(),
        llm_latencies=latencies,
        tool_operations=[(call.operation, call.success) for call in meter.tool_calls],
        coder_test_files=test_files,
        error=result.get("error"),
    )
    _keep(artifacts_dir, run_id, run_result, meter, sandbox, result, acceptance_output)
    return run_result


def _keep(
    artifacts_dir: Path | None,
    run_id: str,
    run_result: RunResult,
    meter: Meter,
    sandbox: Path | None,
    result: dict[str, Any],
    acceptance_output: str,
) -> None:
    if artifacts_dir is not None:
        keep_run_artifacts(
            artifacts_dir, run_id, run_result, meter, sandbox, result.get("step_reports", []), acceptance_output
        )


def run_suite(
    tasks: Sequence[GoldenTask],
    repeats: int,
    make_system: SystemFactory,
    workdir: Path,
    on_result: Callable[[RunResult], None] | None = None,
    artifacts_dir: Path | None = None,
) -> list[RunResult]:
    """Run every task `repeats` times (interleaved, so a slow drift affects tasks evenly)."""
    results = []
    for repeat in range(repeats):
        for task in tasks:
            result = run_task(task, repeat, make_system, workdir, artifacts_dir)
            results.append(result)
            if on_result:
                on_result(result)
    return results
