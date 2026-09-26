"""Tests for the throwaway git sandbox each evaluation run works in.

Real git, fully offline: a working repo with a *local bare* remote, so the Tool agent's commit and
push are genuinely exercised without ever touching GitHub.
"""

import subprocess

from multiagent.evaluation.golden import GoldenTask
from multiagent.evaluation.sandbox import LocalEvalGitTools, prepare_sandbox
from multiagent.tools.git_tools import GitTools


def _task(**overrides):
    params = {
        "id": "t", "category": "bugfix", "goal": "fix it", "expectation": "implement",
        "seed_files": {"stats.py": "def average(n):\n    return 0\n"},
        "acceptance_test": "def test_x():\n    pass\n", "reference_solution": {"stats.py": "x = 1\n"},
    }
    params.update(overrides)
    return GoldenTask(**params)


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def test_prepare_sandbox_writes_the_seed_files_and_commits_them(tmp_path):
    sandbox = prepare_sandbox(_task(), tmp_path)

    assert (sandbox / "stats.py").read_text(encoding="utf-8") == "def average(n):\n    return 0\n"
    assert _git(sandbox, "log", "--format=%s") == "seed"
    assert _git(sandbox, "status", "--porcelain") == ""


def test_prepare_sandbox_works_for_a_task_with_no_seed_files(tmp_path):
    sandbox = prepare_sandbox(_task(seed_files={}), tmp_path)

    assert sandbox.is_dir()
    assert _git(sandbox, "rev-parse", "--is-inside-work-tree") == "true"


def test_the_sandbox_has_a_local_remote_so_a_real_push_works_offline(tmp_path):
    sandbox = prepare_sandbox(_task(), tmp_path)
    tools = GitTools(sandbox)
    (sandbox / "new.py").write_text("x = 1\n", encoding="utf-8")

    assert tools.create_branch("eval/feature").success
    assert tools.commit("add new", ["new.py"]).success
    push = tools.push("eval/feature")

    assert push.success, push.output
    remote = _git(sandbox, "remote", "get-url", "origin")
    assert "eval/feature" in _git(tmp_path, "-C", remote, "branch", "--list")


def test_the_remote_is_local_never_github(tmp_path):
    sandbox = prepare_sandbox(_task(), tmp_path)

    assert "github" not in _git(sandbox, "remote", "get-url", "origin").lower()


def test_pull_request_creation_is_stubbed_and_says_so(tmp_path):
    sandbox = prepare_sandbox(_task(), tmp_path)

    result = LocalEvalGitTools(sandbox).create_pull_request(title="t", body="b")

    assert result.success is True
    assert "not exercised" in result.output
