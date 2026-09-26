"""ToolAgent: the only agent with git/GitHub access, plus the best-effort hardware test runner.

Composes GitTools (deterministic, allowlisted git/gh operations), an injected LLMClient (Ollama,
per REQUIREMENTS.md §3 D4 — CPU-only, so it never contends with the GPU-resident llama-server
used by the Planner/Coder) for the one place an LLM adds real value here — writing a commit
message from a plain-text summary — and a HardwareTestRunner for best-effort device/emulator
checks. Never edits code; that's the Coding agent's job.

`max_retries` here means total attempts for a retried operation, not "retries after the first",
so every retry_with_fallback call in this class uses the same number consistently: pass 2 and
every retried step gets exactly 2 tries, not 2 or 3 depending on which method you're reading.

Only push and PR creation share a circuit breaker: they're the network-dependent operations
prone to a correlated failure mode (GitHub down, auth expired), unlike create_branch/commit
(local, deterministic, and rarely benefit from a retry at all -- retrying a "branch already
exists" error doesn't help). Repeated hardware-test unavailability isn't circuit-broken either:
it's a single best-effort check each time, not a retried operation.
"""

from collections.abc import Sequence

from multiagent.contracts.messages import (
    AgentMessage,
    AgentName,
    MessageStatus,
    ToolExecutionReport,
)
from multiagent.llm.base import LLMClient
from multiagent.resilience import CircuitBreaker, retry_with_fallback
from multiagent.tools.git_tools import GitTools
from multiagent.tools.hardware_test_runner import HardwareTestRunner


class ToolAgent:
    """Executes git/GitHub actions and best-effort hardware tests, reporting each as an AgentMessage."""

    def __init__(
        self,
        git_tools: GitTools,
        llm_client: LLMClient,
        hardware_test_runner: HardwareTestRunner,
        task_id: str,
        max_retries: int = 2,
        push_circuit_breaker: CircuitBreaker | None = None,
    ):
        self._git_tools = git_tools
        self._llm_client = llm_client
        self._hardware_test_runner = hardware_test_runner
        self._task_id = task_id
        self._max_retries = max_retries
        self._push_circuit_breaker = push_circuit_breaker or CircuitBreaker(failure_threshold=max_retries)

    def generate_commit_message(self, summary: str) -> str:
        """Ask the LLM for a one-line commit message; fall back to the raw summary on failure."""

        def _attempt() -> str:
            response = self._llm_client.generate(
                "Write a single-line, conventional-commit-style git commit message "
                f"summarizing this change: {summary}",
                max_tokens=64,
            )
            return response.text.strip()

        result = retry_with_fallback(_attempt, max_attempts=self._max_retries, is_acceptable=bool)
        return result.value if result.succeeded else summary

    def commit_and_push(self, branch: str, summary: str, paths: Sequence[str]) -> AgentMessage:
        if self._push_circuit_breaker.is_open:
            return self._error("commit_and_push", "circuit breaker open after repeated push failures")

        branch_result = self._git_tools.create_branch(branch)
        if not branch_result.success:
            return self._error("create_branch", branch_result.output)

        message_text = self.generate_commit_message(summary)
        commit_result = self._git_tools.commit(message_text, paths)
        if not commit_result.success:
            return self._error("commit", commit_result.output)

        def _push_attempt():
            result = self._git_tools.push(branch)
            if not result.success:
                raise RuntimeError(result.output)
            return result

        push_retry = retry_with_fallback(_push_attempt, max_attempts=self._max_retries)
        if not push_retry.succeeded:
            self._push_circuit_breaker.record_failure()
            return self._error("push", push_retry.last_error or "push failed")

        self._push_circuit_breaker.record_success()
        return self._ok("commit_and_push", f"committed and pushed {branch}: {message_text}")

    def open_pull_request(self, title: str, body: str, base: str = "main") -> AgentMessage:
        if self._push_circuit_breaker.is_open:
            return self._error("create_pull_request", "circuit breaker open after repeated push failures")

        def _attempt():
            result = self._git_tools.create_pull_request(title, body, base)
            if not result.success:
                raise RuntimeError(result.output)
            return result

        retry_result = retry_with_fallback(_attempt, max_attempts=self._max_retries)
        if not retry_result.succeeded:
            self._push_circuit_breaker.record_failure()
            return self._error("create_pull_request", retry_result.last_error or "PR creation failed")

        self._push_circuit_breaker.record_success()
        return self._ok("create_pull_request", retry_result.value.output)

    def run_hardware_tests(self) -> AgentMessage:
        """Best-effort only: unavailability or failure is reported as data, not a system error."""
        result = self._hardware_test_runner.run()
        report = ToolExecutionReport(action="run_hardware_tests", success=result.passed, details=result.output)
        return AgentMessage(agent=AgentName.TOOL, task_id=self._task_id, status=MessageStatus.OK, payload=report)

    def _ok(self, action: str, details: str) -> AgentMessage:
        report = ToolExecutionReport(action=action, success=True, details=details)
        return AgentMessage(agent=AgentName.TOOL, task_id=self._task_id, status=MessageStatus.OK, payload=report)

    def _error(self, action: str, details: str) -> AgentMessage:
        return AgentMessage(
            agent=AgentName.TOOL,
            task_id=self._task_id,
            status=MessageStatus.ERROR,
            error=f"{action} failed: {details}",
        )
