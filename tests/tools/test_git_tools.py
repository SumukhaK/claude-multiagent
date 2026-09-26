"""Tests for the deterministic git/gh wrapper tools, the only tool access given to the Tool
agent (CLAUDE.md §4).

create_branch/commit run against a real, throwaway local git repo (git init in tmp_path) --
these are local-only, offline, and safe to run for real. push/create_pull_request are always
mocked: they'd otherwise hit a real network/remote and, for create_pull_request, the user's own
authenticated `gh` account -- never something a test suite should risk doing for real.
"""

import subprocess

import pytest

from multiagent.tools.git_tools import GitTools


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=tmp_path, check=True)
    return tmp_path


def test_create_branch_succeeds_for_a_valid_name(repo):
    tools = GitTools(repo)

    result = tools.create_branch("feature/add-thing")

    assert result.success is True
    current = subprocess.run(
        ["git", "branch", "--show-current"], cwd=repo, capture_output=True, text=True, check=True
    )
    assert current.stdout.strip() == "feature/add-thing"


def test_create_branch_rejects_a_flag_like_name(repo):
    """A branch name starting with "-" could be misread by git as an option rather than a
    positional argument -- reject it outright instead of trusting git's parser."""
    tools = GitTools(repo)

    with pytest.raises(ValueError):
        tools.create_branch("--upload-pack=/bin/sh")


def test_create_branch_reports_failure_for_a_name_that_already_exists(repo):
    tools = GitTools(repo)
    tools.create_branch("dup")
    tools.checkout("main")

    result = tools.create_branch("dup")

    assert result.success is False


def test_commit_stages_and_commits_the_given_paths(repo):
    tools = GitTools(repo)
    (repo / "new_file.txt").write_text("content\n", encoding="utf-8")

    result = tools.commit("add new_file", ["new_file.txt"])

    assert result.success is True
    log = subprocess.run(["git", "log", "-1", "--format=%s"], cwd=repo, capture_output=True, text=True, check=True)
    assert log.stdout.strip() == "add new_file"


def test_commit_rejects_an_empty_message(repo):
    tools = GitTools(repo)
    (repo / "new_file.txt").write_text("content\n", encoding="utf-8")

    with pytest.raises(ValueError):
        tools.commit("", ["new_file.txt"])


def test_commit_reports_failure_when_there_is_nothing_to_commit(repo):
    tools = GitTools(repo)

    result = tools.commit("nothing changed", [])

    assert result.success is False


def test_push_invokes_git_push_without_touching_the_network(repo, monkeypatch):
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        return subprocess.CompletedProcess(args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    tools = GitTools(repo)

    result = tools.push("feature/x")

    assert result.success is True
    assert captured["args"] == ["git", "push", "-u", "origin", "feature/x"]


def test_push_rejects_a_flag_like_branch_name(repo):
    tools = GitTools(repo)

    with pytest.raises(ValueError):
        tools.push("--force")


def test_push_handles_a_timeout_without_raising(repo, monkeypatch):
    def fake_run(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd=["git", "push"], timeout=5, output="partial", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    tools = GitTools(repo, timeout_seconds=5)

    result = tools.push("feature/x")

    assert result.timed_out is True
    assert result.success is False


def test_create_pull_request_invokes_gh_without_touching_the_network(repo, monkeypatch):
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        return subprocess.CompletedProcess(args, returncode=0, stdout="https://github.com/x/y/pull/1", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    tools = GitTools(repo)

    result = tools.create_pull_request(title="Add thing", body="Does the thing", base="main")

    assert result.success is True
    assert captured["args"] == [
        "gh", "pr", "create", "--title", "Add thing", "--body", "Does the thing", "--base", "main",
    ]


def test_create_pull_request_reports_gh_failure(repo, monkeypatch):
    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args, returncode=1, stdout="", stderr="no commits between main and HEAD")

    monkeypatch.setattr(subprocess, "run", fake_run)
    tools = GitTools(repo)

    result = tools.create_pull_request(title="Add thing", body="Does the thing")

    assert result.success is False
    assert "no commits" in result.output


AWS_KEY = "AKI" + "A" + "ABCDEFGH" + "IJKLMNOP"  # assembled at runtime: no token-shaped literal in source


def _staged_files(repo) -> str:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"], cwd=repo, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def test_commit_refuses_a_file_containing_a_secret_without_echoing_it(repo):
    (repo / "config.py").write_text(f"KEY = '{AWS_KEY}'\n", encoding="utf-8")

    result = GitTools(repo).commit("add config", ["config.py"])

    assert result.success is False
    assert "aws-access-key" in result.output
    assert AWS_KEY not in result.output
    assert _staged_files(repo) == ""


def test_commit_refuses_protected_files_even_when_named_explicitly(repo):
    (repo / ".env").write_text("A=1\n", encoding="utf-8")

    result = GitTools(repo).commit("add env", [".env"])

    assert result.success is False
    assert "protected" in result.output
    assert _staged_files(repo) == ""


@pytest.mark.parametrize("path", ["src", ".", "missing.txt", "../outside.txt"])
def test_commit_only_stages_explicit_existing_files_inside_the_repo(repo, path):
    (repo / "src").mkdir()
    (repo / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")

    result = GitTools(repo).commit("add", [path])

    assert result.success is False
    assert _staged_files(repo) == ""


def test_commit_never_lets_a_path_be_read_as_a_git_option(repo):
    """`git add -A` would stage everything, including files the caller never named."""
    (repo / "untracked.txt").write_text("x\n", encoding="utf-8")

    result = GitTools(repo).commit("add", ["-A"])

    assert result.success is False
    assert _staged_files(repo) == ""


def test_commit_separates_paths_from_options_with_a_double_dash(repo, monkeypatch):
    (repo / "a.txt").write_text("x\n", encoding="utf-8")
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    GitTools(repo).commit("add a", ["a.txt"])

    assert calls[0] == ["git", "add", "--", "a.txt"]


def test_commit_refuses_a_message_containing_a_secret(repo):
    (repo / "a.txt").write_text("x\n", encoding="utf-8")

    result = GitTools(repo).commit(f"add key {AWS_KEY}", ["a.txt"])

    assert result.success is False
    assert AWS_KEY not in result.output
    assert _staged_files(repo) == ""


@pytest.mark.parametrize(("title", "body"), [(f"key {AWS_KEY}", "ok"), ("ok", f"the key is {AWS_KEY}")])
def test_create_pull_request_refuses_a_title_or_body_containing_a_secret(repo, monkeypatch, title, body):
    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("gh must not be invoked when the PR text contains a secret")

    monkeypatch.setattr(subprocess, "run", fail_if_called)

    result = GitTools(repo).create_pull_request(title=title, body=body)

    assert result.success is False
    assert AWS_KEY not in result.output
