"""Tests for the outbound secret scanner.

Fake secrets are assembled at runtime from fragments so no token-shaped literal ever appears in
this repo's source (which would trip GitHub push protection on a public repository).
"""

import pytest

from multiagent.guardrails.secret_scanner import scan_for_secrets


def _fake(*fragments: str) -> str:
    return "".join(fragments)


AWS_KEY = _fake("AKI", "A", "ABCDEFGH", "IJKLMNOP")
GITHUB_TOKEN = _fake("gh", "p_", "a1B2c3D4e5F6g7H8i9J0", "k1L2m3N4o5P6q7R8")
GITHUB_PAT = _fake("github", "_pat_", "11ABCDEFG0123456789", "_abcdefghijklmnop")
API_KEY = _fake("s", "k-", "proj-", "AbCdEfGhIjKlMnOpQrStUv123456")
SLACK = _fake("xo", "xb-", "1234567890-", "abcdefghij")
GOOGLE = _fake("AI", "za", "SyA1B2C3D4E5F6G7H8I9J0K1L2M3N4O5P6Q")
JWT = _fake("ey", "JhbGciOiJIUzI1NiJ9", ".", "ey", "JzdWIiOiIxMjM0NTY3ODkwIn0", ".", "SflKxwRJSMeKKF2QT4fwpMeJf36POk6")
PEM = _fake("-----BEGIN ", "RSA PRIVATE", " KEY-----")


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        (f"aws_key = '{AWS_KEY}'", "aws-access-key"),
        (f"token: {GITHUB_TOKEN}", "github-token"),
        (f"token = {GITHUB_PAT}", "github-token"),
        (f"OPENAI_API_KEY={API_KEY}", "api-key"),
        (f"webhook {SLACK}", "slack-token"),
        (f"key={GOOGLE}", "google-api-key"),
        (f"Authorization: Bearer {JWT}", "jwt"),
        (f"{PEM}\nMIIEvQIBADANBg", "private-key"),
        ("db = 'postgres://admin:s3cretpass@db.internal:5432/app'", "credentials-in-url"),
        ("password = 'Xk9mQ2vL8nR4tY7wB3zC5'", "hardcoded-secret"),
        ('{"api_key": "a8F3kL0pQ9zX2vB7nM4tR1yU6"}', "hardcoded-secret"),
    ],
)
def test_detects_each_kind_of_secret(text, kind):
    assert kind in scan_for_secrets(text)


def test_reports_kinds_never_the_secret_values():
    findings = scan_for_secrets(f"aws_key = '{AWS_KEY}' and token {GITHUB_TOKEN}")

    assert set(findings) == {"aws-access-key", "github-token"}
    assert not any(AWS_KEY in finding or GITHUB_TOKEN in finding for finding in findings)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "def get_password():\n    return prompt('Password: ')",
        "password = get_password_from_keyring()",
        "API_KEY=your-api-key-here",
        "password = 'hunter2'",
        "token = None",
        "The password field must be at least 8 characters.",
        "# set SECRET_KEY in your environment",
        "postgres://localhost:5432/app",
        "https://example.com/docs",
        "sk-learn is a library",
        "x = 'AKIA is the AWS prefix'",
    ],
)
def test_ordinary_code_and_prose_is_not_flagged(text):
    assert scan_for_secrets(text) == []


def test_a_placeholder_assignment_is_not_flagged_but_a_realistic_value_is():
    assert scan_for_secrets("api_key = 'test-key-123'") == []
    assert scan_for_secrets("api_key = 'a8F3kL0pQ9zX2vB7nM4tR1yU6'") == ["hardcoded-secret"]


def test_placeholder_looking_fixtures_are_not_flagged():
    """Model-written tests are full of these; flagging them would block nearly every commit."""
    assert scan_for_secrets('api_key = "test_api_key_1234567890abcdef"') == []
    assert scan_for_secrets("token = 'dummy-token-value-0123456789'") == []
