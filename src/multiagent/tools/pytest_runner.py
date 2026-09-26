"""Sandboxed pytest execution, used by the Coding agent to verify its own work.

Per CLAUDE.md §4: bounded tool execution with explicit timeout handling — always
`sys.executable -m pytest` as an argv list (never a shell string), always confined to the
sandbox root, and every proposed target is validated *before* any subprocess is launched so an
invalid target can never trigger a partial or wrong-directory test run.

Model-written tests are untrusted code, so the subprocess also gets a scrubbed environment (no
secret-looking variables — see subprocess_env.py) and its output goes to a temp file of which
only the tail is read back: a test that prints gigabytes can't balloon this process's memory, and
the tail is where pytest's summary lives. Residual risks (documented in REQUIREMENTS.md §10): the
tests still run with the developer's OS privileges, can use the network, and on timeout Windows
kills the pytest process but not any grandchildren it spawned.
"""

import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from multiagent.tools.filesystem import ReadOnlyFilesystem
from multiagent.tools.subprocess_env import scrubbed_environment


@dataclass(frozen=True)
class TestRunResult:
    passed: bool
    return_code: int
    output: str
    duration_seconds: float
    timed_out: bool = False


def _read_tail(sink: IO[bytes], max_bytes: int) -> str:
    """The last `max_bytes` of what the subprocess wrote, with a marker if anything was cut."""
    sink.flush()
    size = sink.seek(0, os.SEEK_END)
    start = max(0, size - max_bytes)
    sink.seek(start)
    text = sink.read().decode("utf-8", errors="replace")
    if start > 0:
        return f"[... output truncated, showing the last {max_bytes} bytes ...]\n{text}"
    return text


class SandboxedPytestRunner:
    """Runs pytest confined to one project root, with a hard timeout and bounded output."""

    def __init__(
        self,
        project_root: str | Path,
        timeout_seconds: float = 60.0,
        max_output_bytes: int = 20_000,
    ):
        self._sandbox = ReadOnlyFilesystem(project_root)
        self._root = Path(project_root).resolve()
        self._timeout_seconds = timeout_seconds
        self._max_output_bytes = max_output_bytes

    def run(self, targets: Sequence[str] | None = None) -> TestRunResult:
        validated_targets = [self._sandbox.resolve_within_sandbox(t) for t in (targets or [])]
        args = [sys.executable, "-m", "pytest", "-q"]
        args.extend(str(t.relative_to(self._root)) for t in validated_targets)

        started = time.monotonic()
        timed_out = False
        return_code = -1
        with tempfile.TemporaryFile() as sink:
            try:
                completed = subprocess.run(
                    args,
                    cwd=self._root,
                    stdout=sink,
                    stderr=subprocess.STDOUT,
                    env=scrubbed_environment(os.environ),
                    timeout=self._timeout_seconds,
                    check=False,  # a non-zero exit means "tests failed", not a crash to raise on
                )
                return_code = completed.returncode
            except subprocess.TimeoutExpired:
                timed_out = True
            output = _read_tail(sink, self._max_output_bytes)

        return TestRunResult(
            passed=not timed_out and return_code == 0,
            return_code=return_code,
            output=output,
            duration_seconds=time.monotonic() - started,
            timed_out=timed_out,
        )
