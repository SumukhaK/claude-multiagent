"""Tests for ToolAgent: the only agent with git/GitHub access, composing GitTools, an
Ollama-backed commit-message generator, and the best-effort hardware test runner.

Uses a FakeGitTools test double rather than the real GitTools -- GitTools' own subprocess
mechanics already have dedicated tests (test_git_tools.py); these tests are about ToolAgent's
decision logic (call order, retry, circuit-breaker, error reporting), which shouldn't need a
real git repo or network to verify.
"""

import httpx
import pytest

from multiagent.agents.tool.agent import ToolAgent
from multiagent.contracts.messages import MessageStatus, ToolExecutionReport
from multiagent.llm.base import LLMResponse
from multiagent.resilience import CircuitBreaker
from multiagent.tools.git_tools import ToolCommandResult
from multiagent.tools.hardware_test_runner import HardwareTestResult


def _result(success: bool, output: str = "") -> ToolCommandResult:
    return ToolCommandResult(success=success, return_code=0 if success else 1, output=output, duration_seconds=0.01)


class FakeGitTools:
    def __init__(self):
        self.create_branch_result = _result(True)
        self.commit_result = _result(True)
        self.push_results = [_result(True)]
        self.pr_result = _result(True, "https://github.com/x/y/pull/1")
        self.calls: list[tuple] = []

    def create_branch(self, name):
        self.calls.append(("create_branch", name))
        return self.create_branch_result

    def commit(self, message, paths):
        self.calls.append(("commit", message, tuple(paths)))
        return self.commit_result

    def push(self, branch):
        self.calls.append(("push", branch))
        return self.push_results.pop(0) if len(self.push_results) > 1 else self.push_results[0]

    def create_pull_request(self, title, body, base="main"):
        self.calls.append(("create_pull_request", title, body, base))
        return self.pr_result


class FakeLLMClient:
    def __init__(self, text: str = "", error: Exception | None = None):
        self._text = text
        self._error = error

    def generate(self, prompt: str, *, max_tokens: int = 512) -> LLMResponse:
        if self._error is not None:
            raise self._error
        return LLMResponse(text=self._text, prompt_tokens=5, completion_tokens=5, latency_seconds=0.01)


class FakeHardwareTestRunner:
    def __init__(self, result: HardwareTestResult):
        self._result = result

    def run(self, command=None):
        return self._result


@pytest.fixture
def git_tools():
    return FakeGitTools()


def make_agent(git_tools, llm_text="feat: add thing", llm_error=None, breaker=None, hardware_result=None):
    return ToolAgent(
        git_tools=git_tools,
        llm_client=FakeLLMClient(text=llm_text, error=llm_error),
        hardware_test_runner=FakeHardwareTestRunner(
            hardware_result or HardwareTestResult(ran=False, passed=False, output="unavailable")
        ),
        task_id="task-1",
        max_retries=2,
        push_circuit_breaker=breaker,
    )


def test_generate_commit_message_uses_the_llm_output(git_tools):
    agent = make_agent(git_tools, llm_text="feat: add health endpoint")

    assert agent.generate_commit_message("added a health endpoint") == "feat: add health endpoint"


def test_generate_commit_message_falls_back_to_the_summary_when_the_llm_call_fails(git_tools):
    agent = make_agent(git_tools, llm_error=httpx.ConnectError("down"))

    assert agent.generate_commit_message("added a health endpoint") == "added a health endpoint"


def test_generate_commit_message_falls_back_to_the_summary_when_the_llm_returns_nothing(git_tools):
    agent = make_agent(git_tools, llm_text="   ")

    assert agent.generate_commit_message("added a health endpoint") == "added a health endpoint"


def test_commit_and_push_happy_path_calls_git_tools_in_order(git_tools):
    agent = make_agent(git_tools, llm_text="feat: add thing")

    message = agent.commit_and_push(branch="feat/x", summary="added thing", paths=["x.py"])

    assert message.status == MessageStatus.OK
    assert isinstance(message.payload, ToolExecutionReport)
    assert message.payload.success is True
    assert [call[0] for call in git_tools.calls] == ["create_branch", "commit", "push"]
    assert git_tools.calls[1][1] == "feat: add thing"


def test_commit_and_push_stops_and_reports_error_when_branch_creation_fails(git_tools):
    git_tools.create_branch_result = _result(False, "branch already exists")
    agent = make_agent(git_tools)

    message = agent.commit_and_push(branch="feat/x", summary="added thing", paths=["x.py"])

    assert message.status == MessageStatus.ERROR
    assert [call[0] for call in git_tools.calls] == ["create_branch"]


def test_commit_and_push_stops_and_reports_error_when_commit_fails(git_tools):
    git_tools.commit_result = _result(False, "nothing to commit")
    agent = make_agent(git_tools)

    message = agent.commit_and_push(branch="feat/x", summary="added thing", paths=["x.py"])

    assert message.status == MessageStatus.ERROR
    assert [call[0] for call in git_tools.calls] == ["create_branch", "commit"]


def test_commit_and_push_retries_a_failed_push_and_succeeds(git_tools):
    git_tools.push_results = [_result(False, "transient network error"), _result(True)]
    agent = make_agent(git_tools)

    message = agent.commit_and_push(branch="feat/x", summary="added thing", paths=["x.py"])

    assert message.status == MessageStatus.OK
    assert [call[0] for call in git_tools.calls].count("push") == 2


def test_commit_and_push_reports_error_after_push_exhausts_retries(git_tools):
    git_tools.push_results = [_result(False, "still down")]
    agent = make_agent(git_tools)

    message = agent.commit_and_push(branch="feat/x", summary="added thing", paths=["x.py"])

    assert message.status == MessageStatus.ERROR
    assert [call[0] for call in git_tools.calls].count("push") == 2  # max_retries=2


def test_commit_and_push_short_circuits_when_the_breaker_is_already_open(git_tools):
    breaker = CircuitBreaker(failure_threshold=1)
    breaker.record_failure()
    agent = make_agent(git_tools, breaker=breaker)

    message = agent.commit_and_push(branch="feat/x", summary="added thing", paths=["x.py"])

    assert message.status == MessageStatus.ERROR
    assert git_tools.calls == []


def test_open_pull_request_happy_path(git_tools):
    agent = make_agent(git_tools)

    message = agent.open_pull_request(title="Add thing", body="Does the thing")

    assert message.status == MessageStatus.OK
    assert message.payload.success is True
    assert git_tools.calls == [("create_pull_request", "Add thing", "Does the thing", "main")]


def test_open_pull_request_reports_error_after_exhausting_retries(git_tools):
    git_tools.pr_result = _result(False, "no commits between main and HEAD")
    agent = make_agent(git_tools)

    message = agent.open_pull_request(title="Add thing", body="Does the thing")

    assert message.status == MessageStatus.ERROR
    assert len(git_tools.calls) == 2  # max_retries=2


def test_run_hardware_tests_reports_the_runner_result(git_tools):
    agent = make_agent(
        git_tools, hardware_result=HardwareTestResult(ran=True, passed=True, output="1 test passed")
    )

    message = agent.run_hardware_tests()

    assert message.status == MessageStatus.OK
    assert message.payload.success is True
    assert "1 test passed" in message.payload.details


def test_run_hardware_tests_reports_unavailability_as_ok_not_error(git_tools):
    agent = make_agent(
        git_tools, hardware_result=HardwareTestResult(ran=False, passed=False, output="adb not found")
    )

    message = agent.run_hardware_tests()

    assert message.status == MessageStatus.OK
    assert message.payload.success is False
