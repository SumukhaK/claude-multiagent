"""Tests for the best-effort hardware/emulator test runner.

Per REQUIREMENTS.md §7 (non-goals): guaranteeing hardware/emulator test execution is explicitly
out of scope given this laptop's hardware ceiling and the absence of any device/emulator
tooling. This detects that honestly and reports it, rather than pretending to run tests it
can't actually run.
"""

import shutil
import subprocess

import pytest

from multiagent.tools.hardware_test_runner import HardwareTestRunner


def test_is_available_reflects_whether_adb_is_on_path(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    assert HardwareTestRunner().is_available() is False

    monkeypatch.setattr(shutil, "which", lambda _name: r"C:\sdk\platform-tools\adb.exe")
    assert HardwareTestRunner().is_available() is True


def test_run_reports_unavailable_without_launching_a_subprocess_when_adb_is_missing(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _name: None)

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("subprocess.run should not be called when adb is unavailable")

    monkeypatch.setattr(subprocess, "run", fail_if_called)
    runner = HardwareTestRunner()

    result = runner.run()

    assert result.ran is False
    assert result.passed is False
    assert "adb" in result.output.lower()


def test_run_reports_success_when_the_command_succeeds(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/adb")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, returncode=0, stdout="device found", stderr=""),
    )
    runner = HardwareTestRunner()

    result = runner.run()

    assert result.ran is True
    assert result.passed is True
    assert "device found" in result.output


def test_run_reports_failure_when_the_command_fails(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/adb")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, returncode=1, stdout="", stderr="no devices"),
    )
    runner = HardwareTestRunner()

    result = runner.run()

    assert result.ran is True
    assert result.passed is False
    assert "no devices" in result.output


def test_run_handles_a_timeout_without_raising(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/adb")

    def fake_run(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd=["adb"], timeout=5)

    monkeypatch.setattr(subprocess, "run", fake_run)
    runner = HardwareTestRunner(timeout_seconds=5)

    result = runner.run()

    assert result.ran is True
    assert result.passed is False
    assert "timed out" in result.output.lower()


def test_run_defaults_to_adb_devices_when_no_command_given(monkeypatch):
    captured = {}

    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/adb")

    def fake_run(args, **kwargs):
        captured["args"] = args
        return subprocess.CompletedProcess(args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    runner = HardwareTestRunner()

    runner.run()

    assert captured["args"] == ["adb", "devices"]


def test_run_uses_a_custom_command_when_given(monkeypatch):
    captured = {}

    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/adb")

    def fake_run(args, **kwargs):
        captured["args"] = args
        return subprocess.CompletedProcess(args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    runner = HardwareTestRunner()

    runner.run(command=["adb", "shell", "am", "instrument"])

    assert captured["args"] == ["adb", "shell", "am", "instrument"]


@pytest.mark.parametrize(
    "command",
    [["cmd", "/c", "calc"], ["python", "-c", "print(1)"], ["/usr/bin/adb", "devices"], ["ADB.exe", "devices"], []],
)
def test_run_refuses_any_command_that_is_not_adb_and_never_launches_it(monkeypatch, command):
    """`adb` merely existing must not turn this into a way to run any executable."""
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/adb")

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("no subprocess may be launched for a non-adb command")

    monkeypatch.setattr(subprocess, "run", fail_if_called)

    result = HardwareTestRunner().run(command=command)

    assert result.ran is False
    assert result.passed is False
    assert "adb" in result.output


def test_run_scrubs_secret_variables_from_the_environment(monkeypatch):
    captured = {}
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/adb")
    monkeypatch.setenv("DEMO_API_TOKEN", "should-not-be-passed")

    def fake_run(args, **kwargs):
        captured["env"] = kwargs["env"]
        return subprocess.CompletedProcess(args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    HardwareTestRunner().run()

    assert "DEMO_API_TOKEN" not in captured["env"]
    assert "PATH" in captured["env"] or "Path" in captured["env"]
