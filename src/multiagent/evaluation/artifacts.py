"""Keeps the evidence of a run that did not succeed, so it can be inspected afterwards.

Without this a run reported "done" while the hidden test failed left nothing to look at: the
sandbox was thrown away with the temp directory. For each such run one folder is written:

    summary.json          outcome, error, acceptance result and output, per-step reports
    llm_responses.jsonl   every raw model response (prompts are not kept: they follow from the task)
    sandbox/              a copy of the files the agents wrote, without .git and caches

Local debugging output, not for publishing wholesale (it holds model-written code), so it is
gitignored. Successful and correctly refused runs leave nothing behind.
"""

import json
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Any

from multiagent.evaluation.metering import Meter

_NOT_WORTH_KEEPING = ("success", "correctly_refused")
_SANDBOX_JUNK = shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache")


def keep_run_artifacts(
    artifacts_dir: Path,
    run_id: str,
    run_result: Any,
    meter: Meter,
    sandbox: Path | None,
    step_reports: list[Any],
    acceptance_output: str,
) -> None:
    """Write the run's evidence under `artifacts_dir/run_id`, unless the run succeeded or was refused."""
    if run_result.outcome in _NOT_WORTH_KEEPING:
        return
    run_dir = artifacts_dir / run_id
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)

    summary = asdict(run_result) | {
        "acceptance_output": acceptance_output,
        "step_reports": [report.model_dump() for report in step_reports],
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    with (run_dir / "llm_responses.jsonl").open("w", encoding="utf-8") as handle:
        for call in meter.llm_calls:
            entry = {
                "role": call.role,
                "prompt_tokens": call.prompt_tokens,
                "completion_tokens": call.completion_tokens,
                "error": call.error,
                "text": call.response_text,
            }
            handle.write(json.dumps(entry) + "\n")

    if sandbox is not None and sandbox.is_dir():
        shutil.copytree(sandbox, run_dir / "sandbox", ignore=_SANDBOX_JUNK)
