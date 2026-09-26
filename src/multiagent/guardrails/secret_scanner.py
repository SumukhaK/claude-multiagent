"""Outbound secret scanning: catch credentials leaving through model-written code, commit
messages, PR text, or persisted memory.

The mirror image of the input filter: that one stops a user *asking* for secrets; this stops
secrets *leaving*, e.g. a key echoed from context into a commit, or a user pasting one into a
clarification answer that would then be stored on disk and recalled into prompts.

Best-effort and pattern-based, like every guardrail here (CLAUDE.md §6): well-known token
formats plus a conservative hardcoded-assignment rule, tuned to avoid flagging the placeholder
values model-written tests are full of, since a false positive blocks a task. It reports the
*kinds* found, never the secret values, so findings are safe to log.
"""

import re

_TOKEN_PATTERNS = {
    "private-key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY"),
    "aws-access-key": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "github-token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})"),
    "api-key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    "slack-token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
    "google-api-key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    "credentials-in-url": re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s:/@'\"]+:[^\s/@'\"]{3,}@"),
}

_QUOTED_ASSIGNMENT = re.compile(
    r"""\b(?:api[_-]?key|secret[_-]?key|secret|token|passwd|password|access[_-]?key)\b["']?"""
    r"""\s*[:=]\s*["']([^"'\s]{16,})["']""",
    re.IGNORECASE,
)
_PLACEHOLDER_MARKERS = ("test", "example", "dummy", "fake", "placeholder", "changeme", "your", "xxxx")


def _looks_like_a_real_secret(value: str) -> bool:
    lowered = value.lower()
    if any(marker in lowered for marker in _PLACEHOLDER_MARKERS):
        return False
    return len(value) >= 20 and any(c.isdigit() for c in value) and any(c.isalpha() for c in value)


def scan_for_secrets(text: str) -> list[str]:
    """Kinds of secret found in `text` (never the values), in a stable order; [] if none."""
    findings = [kind for kind, pattern in _TOKEN_PATTERNS.items() if pattern.search(text)]
    if any(_looks_like_a_real_secret(match.group(1)) for match in _QUOTED_ASSIGNMENT.finditer(text)):
        findings.append("hardcoded-secret")
    return findings
