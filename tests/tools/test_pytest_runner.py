"""Tests for the sandboxed pytest execution tool, used by the Coding agent to verify its own
work before reporting a step complete.

Per CLAUDE.md §4: bounded, sandboxed tool execution with explicit timeout handling — no shell
string, no arbitrary command, and a proposed test target is validated against the sandbox before
any subprocess is ever launched.
"""

import subprocess
import sys

import pytest

from multiagent.tools.filesystem import SandboxViolationError
from multiagent.tools.pytest_runner import SandboxedPytestRunner


@pytest.fixture
def project(tmp_path):
    (tmp_path / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    (tmp_path / "test_bad.py").write_text("def test_bad():\n    assert False\n", encoding="utf-8")
    return tmp_path


def test_run_reports_passed_for_a_passing_suite(tmp_path):
    (tmp_path / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    runner = SandboxedPytestRunner(tmp_path)

    result = runner.run()

    assert result.passed is True
    assert result.return_code == 0
    assert "1 passed" in result.output


def test_run_reports_failure_for_a_failing_suite(tmp_path):
    (tmp_path / "test_bad.py").write_text("def test_bad():\n    assert False\n", encoding="utf-8")
    runner = SandboxedPytestRunner(tmp_path)

    result = runner.run()

    assert result.passed is False
    assert result.return_code != 0
    assert "1 failed" in result.output


def test_run_can_target_specific_files_only(project):
    runner = SandboxedPytestRunner(project)

    result = runner.run(targets=["test_ok.py"])

    assert result.passed is True
    assert "test_bad" not in result.output


def test_run_rejects_a_target_outside_the_sandbox_without_launching_a_subprocess(
    project, tmp_path_factory, monkeypatch
):
    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("subprocess.run should not be called for an invalid target")

    monkeypatch.setattr(subprocess, "run", fail_if_called)
    outside_file = tmp_path_factory.mktemp("outside") / "test_evil.py"
    outside_file.write_text("def test_evil():\n    assert True\n", encoding="utf-8")
    runner = SandboxedPytestRunner(project)

    with pytest.raises(SandboxViolationError):
        runner.run(targets=[str(outside_file)])


def test_run_handles_a_timeout_without_raising(tmp_path, monkeypatch):
    def fake_run(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd=["pytest"], timeout=5, output="partial stdout", stderr="partial stderr")

    monkeypatch.setattr(subprocess, "run", fake_run)
    runner = SandboxedPytestRunner(tmp_path, timeout_seconds=5)

    result = runner.run()

    assert result.timed_out is True
    assert result.passed is False
    assert "partial stdout" in result.output


def test_run_invokes_pytest_as_a_module_with_the_current_interpreter(tmp_path, monkeypatch):
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["cwd"] = kwargs.get("cwd")
        return subprocess.CompletedProcess(args, returncode=0, stdout="1 passed", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    runner = SandboxedPytestRunner(tmp_path)

    runner.run()

    assert captured["args"][:3] == [sys.executable, "-m", "pytest"]
    assert captured["cwd"] == tmp_path.resolve()
