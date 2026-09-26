"""Deterministic git/gh wrapper tools -- the only tool access given to the Tool agent.

Per CLAUDE.md §4: the Tool agent is the only agent with git/GitHub access, and it gets a fixed
set of purpose-built operations rather than a generic "run this git command" passthrough --
least privilege is structural here, the same way WritableFilesystem has no arbitrary-path
passthrough either. Every command is built as an argv list, never a shell string, so there is no
shell-metacharacter injection surface regardless of what a message/title/body contains. Branch
names are still validated separately: a name starting with "-" could be misread by git's own
argument parser as an option instead of a positional argument (a real, known class of git
argument-injection issue), so that's rejected outright rather than trusted to git.
"""

import subprocess
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from multiagent.guardrails.secret_scanner import scan_for_secrets
from multiagent.tools.filesystem import ReadOnlyFilesystem, SandboxViolationError


@dataclass(frozen=True)
class ToolCommandResult:
    success: bool
    return_code: int
    output: str
    duration_seconds: float
    timed_out: bool = False


def _refusal(reason: str) -> ToolCommandResult:
    """A failed result for something refused before any command ran. Never contains the secret."""
    return ToolCommandResult(
        success=False, return_code=-1, output=f"refusing: {reason}", duration_seconds=0.0
    )


def _reject_flag_like_value(value: str, field_name: str) -> None:
    if not value:
        raise ValueError(f"{field_name} must not be empty")
    if value.startswith("-"):
        raise ValueError(f"{field_name} {value!r} looks like a flag, not a valid value")


class GitTools:
    """Confines git/gh operations to one repo root, with a hard timeout on every call."""

    def __init__(self, repo_root: str | Path, timeout_seconds: float = 30.0):
        self._root = Path(repo_root).resolve()
        self._sandbox = ReadOnlyFilesystem(self._root)
        self._timeout_seconds = timeout_seconds

    def _unstageable_reason(self, paths: Sequence[str]) -> str | None:
        """Why these paths must not be staged, or None. Only explicit existing files inside the
        repo, none protected (e.g. `.env`), none containing a secret (first 200 KB, the same cap
        as every read). No directories or "." -- those would stage files nobody named."""
        for path in paths:
            try:
                resolved = self._sandbox.resolve_within_sandbox(path)
            except SandboxViolationError as exc:
                return str(exc)
            if not resolved.is_file():
                return f"{path!r} is not an existing file (stage files explicitly, no directories or '.')"
            kinds = scan_for_secrets(self._sandbox.read_file(path))
            if kinds:
                return f"{path!r} appears to contain a secret ({', '.join(kinds)})"
        return None

    def _run(self, args: list[str]) -> ToolCommandResult:
        started = time.monotonic()
        try:
            result = subprocess.run(
                args,
                cwd=self._root,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return ToolCommandResult(
                success=False,
                return_code=-1,
                output=(exc.output or "") + (exc.stderr or ""),
                duration_seconds=time.monotonic() - started,
                timed_out=True,
            )
        return ToolCommandResult(
            success=result.returncode == 0,
            return_code=result.returncode,
            output=result.stdout + result.stderr,
            duration_seconds=time.monotonic() - started,
        )

    def create_branch(self, name: str) -> ToolCommandResult:
        _reject_flag_like_value(name, "branch name")
        return self._run(["git", "checkout", "-b", name])

    def checkout(self, branch: str) -> ToolCommandResult:
        _reject_flag_like_value(branch, "branch name")
        return self._run(["git", "checkout", branch])

    def commit(self, message: str, paths: Sequence[str]) -> ToolCommandResult:
        if not message:
            raise ValueError("commit message must not be empty")
        if kinds := scan_for_secrets(message):
            return _refusal(f"the commit message appears to contain a secret ({', '.join(kinds)})")
        if reason := self._unstageable_reason(paths):
            return _refusal(reason)
        if paths:
            add_result = self._run(["git", "add", "--", *paths])
            if not add_result.success:
                return add_result
        return self._run(["git", "commit", "-m", message])

    def push(self, branch: str) -> ToolCommandResult:
        _reject_flag_like_value(branch, "branch name")
        return self._run(["git", "push", "-u", "origin", branch])

    def create_pull_request(self, title: str, body: str, base: str = "main") -> ToolCommandResult:
        if not title:
            raise ValueError("PR title must not be empty")
        if kinds := scan_for_secrets(f"{title} {body}"):
            return _refusal(f"the PR title/body appears to contain a secret ({', '.join(kinds)})")
        return self._run(["gh", "pr", "create", "--title", title, "--body", body, "--base", base])
