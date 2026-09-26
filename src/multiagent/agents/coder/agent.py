"""CoderAgent: implements exactly one plan step -- propose, write, run tests, report -- as an
AgentMessage.

Composes the prompt template, an injected LLMClient (llama.cpp or Ollama), a WritableFilesystem,
the response parser, and a SandboxedPytestRunner. Multi-turn orchestration (calling this
repeatedly across steps, ContextManager integration, retries/escalation across agents) is
Phase 7's job; this is the single-step building block that wires up to.

`max_tokens` defaults to 1536, higher than the Planner's 1024: a coding response contains real
file content, not just short descriptions, so it needs more room, and is correspondingly more
likely to be truncated at a given budget on this model — see REQUIREMENTS.md §8. In practice
this means plan steps must stay small (one function, one small file at a time) to fit inside the
~4096-token per-slot budget alongside the prompt and any code context, which is a real
constraint on how the Planning agent should size its steps, not something the Coder can work
around on its own.

A failing test run is reported with status "ok" and `tests_passed=False`, not status "error" —
it's expected, useful information for the orchestrator's retry policy to act on, not a system
failure. Written files are never rolled back on a failing test run either: a retry attempt can
build on (and fix) them, the way a human developer would rather than discarding the attempt.
Status "error" is reserved for actual execution failures: the LLM call failing, the response not
parsing, or a proposed file path escaping the sandbox — the last of which is validated for
*every* proposed file before *any* of them are written, so one bad path in an otherwise-valid
proposal can't cause a partial write.
"""

import httpx

from multiagent.agents.coder.prompts import render_coder_prompt
from multiagent.agents.coder.response_parser import (
    CodeChangeParsingError,
    parse_code_change_response,
)
from multiagent.contracts.messages import (
    AgentMessage,
    AgentName,
    CodeChangeReport,
    MessageStatus,
    PlanStep,
)
from multiagent.llm.base import LLMClient
from multiagent.tools.filesystem import SandboxViolationError
from multiagent.tools.pytest_runner import SandboxedPytestRunner
from multiagent.tools.writable_filesystem import WritableFilesystem


class CoderAgent:
    """Implements one plan step: propose a test + implementation, write them, run the suite."""

    def __init__(
        self,
        llm_client: LLMClient,
        filesystem: WritableFilesystem,
        test_runner: SandboxedPytestRunner,
        task_id: str,
        max_tokens: int = 1536,
    ):
        if max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        self._llm_client = llm_client
        self._filesystem = filesystem
        self._test_runner = test_runner
        self._task_id = task_id
        self._max_tokens = max_tokens

    def implement_step(self, step: PlanStep, code_context: str = "") -> AgentMessage:
        prompt = render_coder_prompt(step=step, code_context=code_context)

        try:
            response = self._llm_client.generate(prompt, max_tokens=self._max_tokens)
        except httpx.HTTPError as exc:
            return self._error(f"coder LLM call failed: {exc}")

        try:
            proposal = parse_code_change_response(response.text)
        except CodeChangeParsingError as exc:
            return self._error(str(exc))

        all_files = proposal.test_files + proposal.implementation_files
        try:
            for file_change in all_files:
                self._filesystem.resolve_within_sandbox(file_change.path)
        except SandboxViolationError as exc:
            return self._error(f"coder proposed a file path outside the project sandbox: {exc}")

        for file_change in all_files:
            self._filesystem.write_file(file_change.path, file_change.content)

        test_result = self._test_runner.run()

        report = CodeChangeReport(
            step_id=step.step_id,
            files_changed=[file_change.path for file_change in all_files],
            tests_added=[file_change.path for file_change in proposal.test_files],
            tests_passed=test_result.passed,
            summary=proposal.summary,
        )
        return AgentMessage(agent=AgentName.CODER, task_id=self._task_id, status=MessageStatus.OK, payload=report)

    def _error(self, message: str) -> AgentMessage:
        return AgentMessage(
            agent=AgentName.CODER, task_id=self._task_id, status=MessageStatus.ERROR, error=message
        )
