"""Tests for the sandboxed write/delete filesystem tool, given only to the Coding agent.

Per CLAUDE.md §4: least privilege is structural. WritableFilesystem extends the Planner's
read-only sandbox rather than duplicating its path-traversal protection in a second
implementation -- there is exactly one place that decides what counts as "inside the sandbox".
"""

import pytest

from multiagent.tools.filesystem import ReadOnlyFilesystem, SandboxViolationError
from multiagent.tools.writable_filesystem import WritableFilesystem


@pytest.fixture
def project(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("def handler():\n    return 'ok'\n", encoding="utf-8")
    return tmp_path


def test_writable_filesystem_is_also_a_read_only_filesystem(project):
    fs = WritableFilesystem(project)

    assert isinstance(fs, ReadOnlyFilesystem)
    assert "def handler" in fs.read_file("src/app.py")


def test_write_file_creates_a_new_file(project):
    fs = WritableFilesystem(project)

    fs.write_file("src/new_module.py", "def helper():\n    pass\n")

    assert "def helper" in fs.read_file("src/new_module.py")


def test_write_file_overwrites_an_existing_file(project):
    fs = WritableFilesystem(project)

    fs.write_file("src/app.py", "def handler():\n    return 'updated'\n")

    assert "updated" in fs.read_file("src/app.py")


def test_write_file_creates_missing_parent_directories(project):
    fs = WritableFilesystem(project)

    fs.write_file("src/newpkg/newfile.py", "x = 1\n")

    assert fs.read_file("src/newpkg/newfile.py") == "x = 1\n"


def test_write_file_blocks_sandbox_escape(project):
    fs = WritableFilesystem(project / "src")

    with pytest.raises(SandboxViolationError):
        fs.write_file("../evil.py", "malicious = True\n")

    assert not (project / "evil.py").exists()


def test_delete_file_removes_an_existing_file(project):
    fs = WritableFilesystem(project)

    fs.delete_file("src/app.py")

    with pytest.raises(FileNotFoundError):
        fs.read_file("src/app.py")


def test_delete_file_raises_for_a_missing_file(project):
    fs = WritableFilesystem(project)

    with pytest.raises(FileNotFoundError):
        fs.delete_file("src/does_not_exist.py")


def test_delete_file_blocks_sandbox_escape(project, tmp_path_factory):
    fs = WritableFilesystem(project)
    outside_file = tmp_path_factory.mktemp("outside") / "important.txt"
    outside_file.write_text("do not delete me", encoding="utf-8")

    with pytest.raises(SandboxViolationError):
        fs.delete_file(str(outside_file))

    assert outside_file.exists()
