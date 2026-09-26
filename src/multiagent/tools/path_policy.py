"""Which files inside the project no agent may touch.

The sandbox root only stops an agent escaping the project; it did nothing to stop the Planner
reading the project's own `.env` (verified live: `.ENV`, `.env.`, `.env::$DATA`, `sub/../.env`
and a symlink all read it). This is the single place that decides what counts as protected,
reused by every filesystem tool, in the same spirit as there being one sandbox implementation.

Callers pass the path *after* resolving it (so symlinks and `..` are already collapsed to the
real name); each part is still normalised here, because a file that doesn't exist yet -- a write
target -- isn't canonicalised by the OS and Windows ignores case, trailing dots/spaces and
`::stream` suffixes when it later opens the name.
"""

from pathlib import PurePath

_PROTECTED_DIRS = {".git", ".ssh", ".aws", ".gnupg", ".memory"}
# Writing here runs model-written code with real privileges (CI with the repo's secrets).
_WRITE_PROTECTED_DIRS = {".github"}
_PROTECTED_NAMES = {".netrc", ".pypirc", ".npmrc", ".git-credentials", "credentials", "credentials.json"}
_PROTECTED_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".keystore", ".jks"}
_PROTECTED_PREFIXES = ("id_rsa", "id_ed25519", "id_ecdsa", "id_dsa")
_ENV_TEMPLATES = {".env.example", ".env.sample", ".env.template"}


def _normalise(part: str) -> str:
    return part.split(":")[0].rstrip(" .").lower()


def _is_protected_name(name: str) -> bool:
    if name in _ENV_TEMPLATES:
        return False
    if name == ".env" or name.startswith((".env.", ".envrc")) or name.endswith(".env"):
        return True
    if name in _PROTECTED_NAMES or name.startswith(_PROTECTED_PREFIXES):
        return True
    return any(name.endswith(suffix) for suffix in _PROTECTED_SUFFIXES)


def is_protected(relative_path: PurePath, *, for_write: bool) -> bool:
    """True if `relative_path` (relative to the sandbox root, already resolved) is off limits."""
    parts = [normalised for normalised in map(_normalise, relative_path.parts) if normalised]
    if not parts:
        return False
    directories = set(parts[:-1]) | ({parts[-1]} if parts[-1] in _PROTECTED_DIRS else set())
    if directories & _PROTECTED_DIRS:
        return True
    if for_write and (set(parts) & _WRITE_PROTECTED_DIRS):
        return True
    return _is_protected_name(parts[-1])
