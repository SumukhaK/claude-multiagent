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

import ast

import httpx
from pyflakes.checker import Checker
from pyflakes.messages import UndefinedName

from multiagent.agents.coder.prompts import render_coder_prompt
from multiagent.agents.coder.schemas import CodeChangeProposal, ProposedFile
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
        constrain_json: bool = False,
        max_report_file_chars: int = 3000,
        max_report_output_chars: int = 1500,
    ):
        if max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        self._llm_client = llm_client
        self._filesystem = filesystem
        self._test_runner = test_runner
        self._task_id = task_id
        self._max_tokens = max_tokens
        self._constrain_json = constrain_json
        self._max_report_file_chars = max_report_file_chars
        self._max_report_output_chars = max_report_output_chars

    def implement_step(
        self, step: PlanStep, code_context: str = "", goal: str = "", feedback: str = ""
    ) -> AgentMessage:
        prompt = render_coder_prompt(
            step=step,
            code_context=code_context,
            constrained=self._constrain_json,
            goal=goal,
            feedback=feedback,
        )

        try:
            if self._constrain_json:
                response = self._llm_client.generate(
                    prompt,
                    max_tokens=self._max_tokens,
                    json_schema=CodeChangeProposal.model_json_schema(),
                )
            else:
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
                self._filesystem.validate_write(file_change.path, file_change.content)
        except SandboxViolationError as exc:
            return self._error(f"coder proposed a write that violates the project sandbox policy: {exc}")

        try:
            for file_change in all_files:
                self._filesystem.write_file(file_change.path, file_change.content)
        except OSError as exc:
            return self._error(f"coder could not write its proposed files: {exc}")

        syntax_errors = self._python_syntax_errors(all_files)
        # Only checked when there are no syntax errors: a file that doesn't parse can't be
        # checked for undefined names either, and is already reported above.
        undefined_name_errors = [] if syntax_errors else self._undefined_names(all_files)
        static_errors = syntax_errors + undefined_name_errors
        if static_errors:
            # Certain to fail pytest collection or every test in the file either way, so skip
            # running it: both checks are instant and precise (file, line, the exact defect),
            # unlike a multi-KB pytest traceback -- found live, see failed_experiment.md 10 (the
            # syntax check) and TRACKER.md 2026-09-27 (undefined names: a 95-attempt survey of
            # real failed runs found a forgotten import was the single largest cause, 35%, of the
            # Coder's own tests failing every retry).
            tests_passed, test_output = False, "\n".join(static_errors)
        else:
            test_result = self._test_runner.run()
            tests_passed, test_output = test_result.passed, test_result.output

        report = CodeChangeReport(
            step_id=step.step_id,
            files_changed=[file_change.path for file_change in all_files],
            tests_added=[file_change.path for file_change in proposal.test_files],
            tests_passed=tests_passed,
            summary=proposal.summary,
            file_contents={
                file_change.path: self._capped(file_change.content, self._max_report_file_chars)
                for file_change in all_files
            },
            test_output=self._capped(test_output, self._max_report_output_chars),
        )
        return AgentMessage(agent=AgentName.CODER, task_id=self._task_id, status=MessageStatus.OK, payload=report)

    @staticmethod
    def _python_syntax_errors(files: list[ProposedFile]) -> list[str]:
        """One precise message per `.py` file that isn't valid Python, or an empty list."""
        errors = []
        for file_change in files:
            if not file_change.path.endswith(".py"):
                continue
            try:
                ast.parse(file_change.content, filename=file_change.path)
            except SyntaxError as exc:
                errors.append(f"SyntaxError in {file_change.path}, line {exc.lineno}: {exc.msg}")
        return errors

    @staticmethod
    def _undefined_names(files: list[ProposedFile]) -> list[str]:
        """One precise message per `.py` file that uses a name it never imported or defined --
        found live to be the single largest cause of the Coder's own tests failing every retry
        (a 95-attempt survey of real failed runs, TRACKER.md 2026-09-27: 35%, usually a forgotten
        `import` in a test file or the implementation itself). pyflakes checks each file on its
        own, which is exactly what's wanted: a test file correctly importing a sibling
        implementation file is never flagged, only a name genuinely never bound anywhere in that
        one file is. Deliberately narrow -- only UndefinedName, not e.g. unused imports, which
        are untidy but not a certain failure worth pre-empting pytest for."""
        errors = []
        for file_change in files:
            if not file_change.path.endswith(".py"):
                continue
            try:
                tree = ast.parse(file_change.content, filename=file_change.path)
            except SyntaxError:
                continue  # already reported by _python_syntax_errors
            for message in Checker(tree, filename=file_change.path).messages:
                if isinstance(message, UndefinedName):
                    errors.append(
                        f"Undefined name in {file_change.path}, line {message.lineno}: "
                        f"{message.message % message.message_args}"
                    )
        return errors

    @staticmethod
    def _capped(content: str, limit: int) -> str:
        """Bounded copy of some evidence (a file, test output): so one huge one can't crowd out
        the next prompt it's fed back into."""
        if len(content) <= limit:
            return content
        return content[:limit] + " ...[truncated]"

    def _error(self, message: str) -> AgentMessage:
        return AgentMessage(
            agent=AgentName.CODER, task_id=self._task_id, status=MessageStatus.ERROR, error=message
        )
