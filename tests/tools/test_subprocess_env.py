"""Tests for scrubbing secrets out of the environment a sandboxed subprocess inherits.

Model-written tests run in a pytest subprocess; without this they could read every secret in
the parent's environment (verified live before the fix).
"""

import pytest

from multiagent.tools.subprocess_env import scrubbed_environment


@pytest.mark.parametrize(
    "name",
    ["OPENAI_API_KEY", "GITHUB_TOKEN", "gh_token", "AWS_SECRET_ACCESS_KEY", "DB_PASSWORD", "MYSQL_PASSWD",
     "GOOGLE_CREDENTIALS", "SSH_AUTH_SOCK", "SIGNING_PRIVATE_KEY", "LANGSMITH_API_KEY"],
)
def test_secret_looking_variables_are_removed(name):
    assert name not in scrubbed_environment({name: "value", "PATH": "/bin"})


@pytest.mark.parametrize("name", ["PATH", "SYSTEMROOT", "TEMP", "USERPROFILE", "PYTHONPATH", "VIRTUAL_ENV", "MY_SETTING"])
def test_ordinary_variables_are_kept(name):
    assert scrubbed_environment({name: "value"})[name] == "value"


def test_the_input_mapping_is_not_mutated():
    original = {"API_TOKEN": "x", "PATH": "/bin"}

    scrubbed_environment(original)

    assert original == {"API_TOKEN": "x", "PATH": "/bin"}
