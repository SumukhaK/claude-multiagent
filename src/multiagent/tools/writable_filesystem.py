"""Sandboxed read/write/delete filesystem access, given only to the Coding agent.

Per CLAUDE.md §4: the Coding agent needs to create and modify files, unlike the read-only
Planning agent. This extends ReadOnlyFilesystem rather than duplicating its sandbox-escape
protection — there is exactly one implementation of "what counts as inside the sandbox", reused
by both agents' tools.
"""

from multiagent.tools.filesystem import ReadOnlyFilesystem


class WritableFilesystem(ReadOnlyFilesystem):
    """Read, write, and delete access, still confined to the sandbox root."""

    def write_file(self, relative_path: str, content: str) -> None:
        path = self.resolve_within_sandbox(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        # newline="" disables platform newline translation (Windows would otherwise turn every
        # \n into \r\n), so what's written matches exactly what the caller specified -
        # read_file() reads raw bytes with no translation either, so this keeps them consistent.
        path.write_text(content, encoding="utf-8", newline="")

    def delete_file(self, relative_path: str) -> None:
        path = self.resolve_within_sandbox(relative_path)
        if not path.is_file():
            raise FileNotFoundError(relative_path)
        path.unlink()
