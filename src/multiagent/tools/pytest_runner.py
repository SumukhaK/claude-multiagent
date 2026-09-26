"""Sandboxed pytest execution, used by the Coding agent to verify its own work.

Per CLAUDE.md §4: bounded tool execution with explicit timeout handling — always
`sys.executable -m pytest` as an argv list (never a shell string), always confined to the
sandbox root, and every proposed target is validated *before* any subprocess is launched so an
invalid target can never trigger a partial or wrong-directory test run.
"""

import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from multiagent.tools.filesystem import ReadOnlyFilesystem


@dataclass(frozen=True)
class TestRunResult:
    passed: bool
    return_code: int
    output: str
    duration_seconds: float
    timed_out: bool = False


class SandboxedPytestRunner:
    """Runs pytest confined to one project root, with a hard timeout."""

    def __init__(self, project_root: str | Path, timeout_seconds: float = 60.0):
        self._sandbox = ReadOnlyFilesystem(project_root)
        self._root = Path(project_root).resolve()
        self._timeout_seconds = timeout_seconds

    def run(self, targets: Sequence[str] | None = None) -> TestRunResult:
        validated_targets = [self._sandbox.resolve_within_sandbox(t) for t in (targets or [])]
        args = [sys.executable, "-m", "pytest", "-q"]
        args.extend(str(t.relative_to(self._root)) for t in validated_targets)

        started = time.monotonic()
        try:
            result = subprocess.run(
                args,
                cwd=self._root,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
                check=False,  # a non-zero exit means "tests failed", not a crash to raise on
            )
        except subprocess.TimeoutExpired as exc:
            return TestRunResult(
                passed=False,
                return_code=-1,
                output=(exc.output or "") + (exc.stderr or ""),
                duration_seconds=time.monotonic() - started,
                timed_out=True,
            )

        return TestRunResult(
            passed=result.returncode == 0,
            return_code=result.returncode,
            output=result.stdout + result.stderr,
            duration_seconds=time.monotonic() - started,
        )
