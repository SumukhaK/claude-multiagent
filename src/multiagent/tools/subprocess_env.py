"""The environment a sandboxed subprocess is allowed to inherit.

Model-written tests run in a pytest subprocess. By default a child inherits the parent's whole
environment, so a test could read every API key and token the developer has exported (verified
live before this existed). Secret-looking variables are dropped by *name*; everything else
(PATH, SYSTEMROOT, TEMP, ...) is kept, since a name-based denylist is far less likely to break
the interpreter than an allowlist of "safe" variables.

Deliberately not applied to GitTools: `git`/`gh` legitimately need their credentials.
"""

from collections.abc import Mapping

_SECRET_NAME_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL", "AUTH", "PRIVATE")


def scrubbed_environment(environ: Mapping[str, str]) -> dict[str, str]:
    """A copy of `environ` without secret-looking variables (matched case-insensitively by name)."""
    return {
        name: value
        for name, value in environ.items()
        if not any(marker in name.upper() for marker in _SECRET_NAME_MARKERS)
    }
