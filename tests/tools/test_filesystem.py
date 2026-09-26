"""Tests for the sandboxed read-only filesystem tool.

Per CLAUDE.md §4: the Planning agent gets read-only access, confined to the project root — never
write, never execute, never able to escape the sandbox via path traversal.
"""

import pytest

from multiagent.tools.filesystem import ReadOnlyFilesystem, SandboxViolationError


@pytest.fixture
def project(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("def handler():\n    return 'ok'\n", encoding="utf-8")
    (tmp_path / "src" / "util.py").write_text("def helper():\n    pass\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# demo project\n", encoding="utf-8")
    return tmp_path


def test_read_file_returns_its_contents(project):
    fs = ReadOnlyFilesystem(project)

    content = fs.read_file("src/app.py")

    assert "def handler" in content


def test_read_file_truncates_at_max_bytes(project):
    fs = ReadOnlyFilesystem(project)

    content = fs.read_file("src/app.py", max_bytes=5)

    assert len(content) <= 5


def test_read_file_raises_for_a_missing_file(project):
    fs = ReadOnlyFilesystem(project)

    with pytest.raises(FileNotFoundError):
        fs.read_file("src/does_not_exist.py")


def test_read_file_blocks_parent_directory_traversal(project):
    fs = ReadOnlyFilesystem(project / "src")

    with pytest.raises(SandboxViolationError):
        fs.read_file("../README.md")


def test_read_file_blocks_an_absolute_path_escaping_the_sandbox(project, tmp_path_factory):
    fs = ReadOnlyFilesystem(project)
    outside_file = tmp_path_factory.mktemp("outside") / "secret.txt"
    outside_file.write_text("do not read me", encoding="utf-8")

    with pytest.raises(SandboxViolationError):
        fs.read_file(str(outside_file))


def test_list_files_returns_relative_paths_matching_the_pattern(project):
    fs = ReadOnlyFilesystem(project)

    files = fs.list_files("src/*.py")

    assert files == ["src/app.py", "src/util.py"]


def test_list_files_defaults_to_everything_under_the_root(project):
    fs = ReadOnlyFilesystem(project)

    files = fs.list_files()

    assert "README.md" in files
    assert "src/app.py" in files


def test_search_text_finds_matching_lines_with_location(project):
    fs = ReadOnlyFilesystem(project)

    matches = fs.search_text("def ", pattern="src/*.py")

    assert ("src/app.py", 1, "def handler():") in matches
    assert ("src/util.py", 1, "def helper():") in matches


def test_search_text_returns_nothing_for_no_matches(project):
    fs = ReadOnlyFilesystem(project)

    matches = fs.search_text("does_not_appear_anywhere")

    assert matches == []


def test_filesystem_tool_has_no_write_or_delete_methods(project):
    fs = ReadOnlyFilesystem(project)

    assert not hasattr(fs, "write_file")
    assert not hasattr(fs, "delete_file")
