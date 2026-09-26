"""The throwaway git sandbox each evaluation run works in.

A working repo with a *local bare* remote, so the Tool agent's commit and push are genuinely
exercised — real git, fully offline, never GitHub. Pull-request creation needs a real GitHub
remote and can't be exercised this way, so it is stubbed *and says so*; the report excludes it
from the tool-success metric (otherwise a stub returning success would inflate it).
"""

import subprocess
from pathlib import Path

from multiagent.evaluation.golden import GoldenTask
from multiagent.tools.git_tools import GitTools, ToolCommandResult


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


def prepare_sandbox(task: GoldenTask, root: Path) -> Path:
    """Create `root/work` (seed files committed as "seed") with a local bare remote `root/origin.git`."""
    remote = root / "origin.git"
    work = root / "work"
    remote.mkdir(parents=True)
    work.mkdir()
    _git(remote, "init", "--bare", "-b", "main")

    _git(work, "init", "-b", "main")
    _git(work, "config", "user.email", "eval@example.invalid")
    _git(work, "config", "user.name", "eval")
    for path, content in task.seed_files.items():
        (work / path).write_text(content, encoding="utf-8")
    _git(work, "add", "-A")
    _git(work, "commit", "--allow-empty", "-m", "seed")
    _git(work, "remote", "add", "origin", str(remote))
    _git(work, "push", "-u", "origin", "main")
    return work


class LocalEvalGitTools(GitTools):
    """GitTools whose PR creation is a labelled stub: there is no GitHub remote to open one on."""

    def create_pull_request(self, title: str, body: str, base: str = "main") -> ToolCommandResult:
        return ToolCommandResult(
            success=True,
            return_code=0,
            output="eval: PR creation not exercised (local remote only)",
            duration_seconds=0.0,
        )
