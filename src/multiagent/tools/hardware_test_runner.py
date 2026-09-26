"""Best-effort hardware/emulator test execution for the Tool agent.

Per REQUIREMENTS.md §7 (explicit non-goal): guaranteeing hardware/emulator test execution is out
of scope given this laptop's hardware ceiling. There's also no Android app or device/emulator
tooling on this machine yet (the Compose frontend is a later phase) -- this detects that
honestly and reports it, rather than pretending to run tests it can't actually run.
"""

import shutil
import subprocess
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class HardwareTestResult:
    ran: bool
    passed: bool
    output: str
    duration_seconds: float = 0.0


class HardwareTestRunner:
    """Runs a device/emulator command via adb if it's available; otherwise reports unavailability."""

    def __init__(self, timeout_seconds: float = 120.0):
        self._timeout_seconds = timeout_seconds

    def is_available(self) -> bool:
        return shutil.which("adb") is not None

    def run(self, command: list[str] | None = None) -> HardwareTestResult:
        if not self.is_available():
            return HardwareTestResult(
                ran=False,
                passed=False,
                output="adb not found -- no device/emulator tooling available on this machine",
            )

        args = command or ["adb", "devices"]
        started = time.monotonic()
        try:
            result = subprocess.run(
                args, capture_output=True, text=True, timeout=self._timeout_seconds, check=False
            )
        except subprocess.TimeoutExpired:
            return HardwareTestResult(
                ran=True,
                passed=False,
                output="hardware test command timed out",
                duration_seconds=time.monotonic() - started,
            )
        return HardwareTestResult(
            ran=True,
            passed=result.returncode == 0,
            output=result.stdout + result.stderr,
            duration_seconds=time.monotonic() - started,
        )
