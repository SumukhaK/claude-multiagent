"""Sandboxed read/write/delete filesystem access, given only to the Coding agent.

Per CLAUDE.md §4: the Coding agent needs to create and modify files, unlike the read-only
Planning agent. This extends ReadOnlyFilesystem rather than duplicating its sandbox-escape
protection — there is exactly one implementation of "what counts as inside the sandbox", reused
by both agents' tools.
"""

from pathlib import Path

from multiagent.tools.filesystem import ReadOnlyFilesystem, SandboxViolationError


class WritableFilesystem(ReadOnlyFilesystem):
    """Read, write, and delete access, still confined to the sandbox root and protected paths."""

    def __init__(self, root: str | Path, max_write_bytes: int = 200_000):
        super().__init__(root)
        self._max_write_bytes = max_write_bytes

    def validate_write(self, relative_path: str, content: str) -> Path:
        """Check a write against the sandbox, protected-path and size policy without touching the
        filesystem, so a caller can validate a whole batch before writing any of it."""
        path = self.resolve_within_sandbox(relative_path, for_write=True)
        if len(content.encode("utf-8")) > self._max_write_bytes:
            raise SandboxViolationError(
                f"{relative_path!r} content exceeds the {self._max_write_bytes}-byte write limit"
            )
        return path

    def write_file(self, relative_path: str, content: str) -> None:
        path = self.validate_write(relative_path, content)
        path.parent.mkdir(parents=True, exist_ok=True)
        # newline="" disables platform newline translation (Windows would otherwise turn every
        # LF into CRLF), so what's written matches exactly what the caller specified -
        # read_file() reads raw bytes with no translation either, so this keeps them consistent.
        path.write_text(content, encoding="utf-8", newline="")

    def delete_file(self, relative_path: str) -> None:
        path = self.resolve_within_sandbox(relative_path, for_write=True)
        if not path.is_file():
            raise FileNotFoundError(relative_path)
        path.unlink()
