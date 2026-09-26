"""Sandboxed read-only filesystem access for the Planning agent.

Per CLAUDE.md §4: the Planning agent must read existing code before planning anything, but gets
only read access, confined to the project root — least privilege, and no way to escape the
sandbox via path traversal (`../`, an absolute path, a symlink resolving outside the root).
"""

from pathlib import Path


class SandboxViolationError(ValueError):
    """Raised when a requested path would resolve outside the sandbox root."""


class ReadOnlyFilesystem:
    """Read-only view of one directory tree. Deliberately has no write/delete methods."""

    def __init__(self, root: str | Path):
        self._root = Path(root).resolve()

    def _resolve(self, relative_path: str) -> Path:
        candidate = (self._root / relative_path).resolve()
        if not candidate.is_relative_to(self._root):
            raise SandboxViolationError(f"{relative_path!r} escapes the sandbox root")
        return candidate

    def resolve_within_sandbox(self, relative_path: str) -> Path:
        """Validate (and return) the absolute path for `relative_path`, without touching the
        filesystem or requiring it to exist. Lets a caller (e.g. the Coding agent, validating a
        whole batch of proposed file changes before writing any of them) check a path is safe
        up front rather than discovering a violation partway through."""
        return self._resolve(relative_path)

    def read_file(self, relative_path: str, max_bytes: int = 200_000) -> str:
        """Read a file's contents, truncated to `max_bytes` (a safety net, not a token budget —
        callers that care about the model's context budget should size/summarize further)."""
        path = self._resolve(relative_path)
        if not path.is_file():
            raise FileNotFoundError(relative_path)
        return path.read_bytes()[:max_bytes].decode("utf-8", errors="replace")

    def list_files(self, pattern: str = "**/*") -> list[str]:
        """List files under the root matching `pattern`, as sandbox-relative POSIX-style paths."""
        return sorted(
            str(path.relative_to(self._root)).replace("\\", "/")
            for path in self._root.glob(pattern)
            if path.is_file()
        )

    def search_text(self, needle: str, pattern: str = "**/*.py") -> list[tuple[str, int, str]]:
        """Return (relative_path, line_number, line_text) for every line containing `needle`."""
        matches: list[tuple[str, int, str]] = []
        for relative_path in self.list_files(pattern):
            content = self.read_file(relative_path)
            for line_number, line in enumerate(content.splitlines(), start=1):
                if needle in line:
                    matches.append((relative_path, line_number, line))
        return matches
