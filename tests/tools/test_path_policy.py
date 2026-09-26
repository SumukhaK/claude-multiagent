"""Tests for the protected-path policy: files inside the project that no agent may read or write.

The sandbox root only stops escaping the project; it did nothing to stop the Planner reading the
project's own `.env` (verified live before this policy existed). This is the single place that
decides what counts as protected, reused by every filesystem tool.
"""

from pathlib import PurePosixPath

import pytest

from multiagent.tools.path_policy import is_protected


@pytest.mark.parametrize(
    "path",
    [
        ".env", ".ENV", ".env.", ".env ", ".env::$DATA", ".env.local", ".env.production",
        "config/.env", "sub/.Env",
        ".git/config", ".git/hooks/pre-commit", "vendor/.git/HEAD",
        "keys/server.pem", "certs/tls.KEY", "id_rsa", "home/id_ed25519", "cert.p12",
        ".ssh/config", ".aws/credentials", ".gnupg/pubring.kbx",
        ".netrc", ".pypirc", ".git-credentials", "credentials.json",
        ".memory/collection/multiagent/storage.sqlite",
    ],
)
def test_sensitive_paths_are_protected_for_reading(path):
    assert is_protected(PurePosixPath(path), for_write=False) is True


@pytest.mark.parametrize(
    "path",
    [
        "src/app.py", "README.md", ".env.example", ".env.sample", "environment.py", "envs/prod.txt",
        "docs/keys.md", "tests/test_git_tools.py", ".gitignore", ".github/workflows/ci.yml", "gitea/x.py",
    ],
)
def test_ordinary_paths_are_not_protected_for_reading(path):
    assert is_protected(PurePosixPath(path), for_write=False) is False


@pytest.mark.parametrize("path", [".github/workflows/ci.yml", ".github/CODEOWNERS", "sub/.GitHub/x.yml"])
def test_ci_config_is_protected_for_writing_only(path):
    """A PR that edits a workflow runs model-written code in CI with the repo's secrets."""
    assert is_protected(PurePosixPath(path), for_write=True) is True
    assert is_protected(PurePosixPath(path), for_write=False) is False


def test_the_project_root_itself_is_not_protected():
    assert is_protected(PurePosixPath("."), for_write=True) is False
