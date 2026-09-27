"""Tests for CoderAgent: implements one plan step end-to-end -- propose, write, run tests,
report -- as an AgentMessage.

Uses a real WritableFilesystem + SandboxedPytestRunner against tmp_path (not mocked) for the
happy-path and test-failure cases, so pass/fail detection and the all-or-nothing sandbox
validation are proven against real file I/O and a real pytest subprocess, not just assumed.
"""

import json

import httpx
import pytest

from multiagent.agents.coder.agent import CoderAgent
from multiagent.contracts.messages import CodeChangeReport, MessageStatus, PlanStep
from multiagent.llm.base import LLMResponse
from multiagent.tools.pytest_runner import SandboxedPytestRunner
from multiagent.tools.writable_filesystem import WritableFilesystem


class FakeLLMClient:
    def __init__(self, text: str = "", error: Exception | None = None):
        self._text = text
        self._error = error
        self.last_prompt: str | None = None
        self.last_json_schema: dict | None = None

    def generate(
        self, prompt: str, *, max_tokens: int = 512, json_schema: dict | None = None
    ) -> LLMResponse:
        self.last_prompt = prompt
        self.last_json_schema = json_schema
        if self._error is not None:
            raise self._error
        return LLMResponse(text=self._text, prompt_tokens=10, completion_tokens=10, latency_seconds=0.1)


def _proposal_json(test_content: str, impl_content: str) -> str:
    return json.dumps(
        {
            "kind": "code_change",
            "step_id": 1,
            "test_files": [{"path": "test_calc.py", "content": test_content}],
            "implementation_files": [{"path": "calc.py", "content": impl_content}],
            "summary": "added add()",
        }
    )


@pytest.fixture
def agent_factory(tmp_path):
    def make(llm_client, **kwargs):
        return CoderAgent(
            llm_client=llm_client,
            filesystem=WritableFilesystem(tmp_path),
            test_runner=SandboxedPytestRunner(tmp_path),
            task_id="task-1",
            **kwargs,
        )

    return make


def test_implement_step_writes_files_and_reports_passing_tests(tmp_path, agent_factory):
    test_content = "from calc import add\n\ndef test_add():\n    assert add(1, 2) == 3\n"
    impl_content = "def add(a, b):\n    return a + b\n"
    llm = FakeLLMClient(text=_proposal_json(test_content, impl_content))
    agent = agent_factory(llm)

    message = agent.implement_step(PlanStep(step_id=1, description="add add()"))

    assert message.status == MessageStatus.OK
    assert isinstance(message.payload, CodeChangeReport)
    assert message.payload.tests_passed is True
    assert (tmp_path / "calc.py").read_text(encoding="utf-8") == impl_content
    assert (tmp_path / "test_calc.py").exists()


def test_implement_step_reports_failing_tests_without_rolling_back_the_files(tmp_path, agent_factory):
    """A failing test run is data for the orchestrator's retry policy to act on, not a system
    error -- and the files stay written so a retry can build on (and fix) them, the way a human
    developer would rather than discarding the attempt."""
    test_content = "from calc import add\n\ndef test_add():\n    assert add(1, 2) == 3\n"
    wrong_impl_content = "def add(a, b):\n    return a - b\n"
    llm = FakeLLMClient(text=_proposal_json(test_content, wrong_impl_content))
    agent = agent_factory(llm)

    message = agent.implement_step(PlanStep(step_id=1, description="add add()"))

    assert message.status == MessageStatus.OK
    assert message.payload.tests_passed is False
    assert (tmp_path / "calc.py").exists()


def test_implement_step_returns_error_when_the_llm_call_fails(agent_factory):
    llm = FakeLLMClient(error=httpx.ConnectError("connection refused"))
    agent = agent_factory(llm)

    message = agent.implement_step(PlanStep(step_id=1, description="add add()"))

    assert message.status == MessageStatus.ERROR
    assert message.payload is None


def test_implement_step_returns_error_when_the_response_cannot_be_parsed(agent_factory):
    llm = FakeLLMClient(text="I don't think I can help with that.")
    agent = agent_factory(llm)

    message = agent.implement_step(PlanStep(step_id=1, description="add add()"))

    assert message.status == MessageStatus.ERROR


def test_implement_step_returns_error_when_the_proposal_has_no_test_files(agent_factory):
    """TDD enforcement, exercised end to end through the agent, not just the schema in isolation."""
    llm = FakeLLMClient(
        text='{"kind": "code_change", "step_id": 1, "test_files": [], '
        '"implementation_files": [{"path": "calc.py", "content": "def add(a, b): return a + b"}], '
        '"summary": "no tests"}'
    )
    agent = agent_factory(llm)

    message = agent.implement_step(PlanStep(step_id=1, description="add add()"))

    assert message.status == MessageStatus.ERROR
    assert "test_files" in message.error


def test_implement_step_rejects_a_sandbox_escape_without_writing_any_file(tmp_path, agent_factory):
    """All-or-nothing: a proposal with one bad path must not write even its other, valid files."""
    llm = FakeLLMClient(
        text='{"kind": "code_change", "step_id": 1, '
        '"test_files": [{"path": "test_ok.py", "content": "def test_ok(): assert True"}], '
        '"implementation_files": [{"path": "../evil.py", "content": "evil = True"}], '
        '"summary": "escape attempt"}'
    )
    agent = agent_factory(llm)

    message = agent.implement_step(PlanStep(step_id=1, description="add add()"))

    assert message.status == MessageStatus.ERROR
    assert not (tmp_path / "test_ok.py").exists()
    assert not (tmp_path.parent / "evil.py").exists()


def test_implement_step_includes_the_step_and_code_context_in_the_prompt(agent_factory):
    llm = FakeLLMClient(text=_proposal_json("def test_x(): pass", "def x(): pass"))
    agent = agent_factory(llm)

    agent.implement_step(PlanStep(step_id=1, description="add x()"), code_context="def old(): pass")

    assert "add x()" in llm.last_prompt
    assert "def old(): pass" in llm.last_prompt


@pytest.mark.parametrize("bad_max_tokens", [0, -1])
def test_coder_agent_rejects_a_non_positive_max_tokens_at_construction(tmp_path, bad_max_tokens):
    with pytest.raises(ValueError):
        CoderAgent(
            llm_client=FakeLLMClient(),
            filesystem=WritableFilesystem(tmp_path),
            test_runner=SandboxedPytestRunner(tmp_path),
            task_id="task-1",
            max_tokens=bad_max_tokens,
        )


def _two_file_proposal(second_path: str, second_content: str = "x = 1\n") -> str:
    return json.dumps(
        {
            "kind": "code_change",
            "step_id": 1,
            "test_files": [{"path": "test_ok.py", "content": "def test_ok():\n    assert True\n"}],
            "implementation_files": [{"path": second_path, "content": second_content}],
            "summary": "policy check",
        }
    )


@pytest.mark.parametrize("bad_path", [".git/hooks/pre-commit", ".env", ".github/workflows/ci.yml"])
def test_implement_step_rejects_protected_paths_without_writing_any_file(tmp_path, agent_factory, bad_path):
    """A git hook or CI workflow is code that runs with real privileges; the valid test file
    proposed alongside it must not be written either (all-or-nothing)."""
    agent = agent_factory(FakeLLMClient(text=_two_file_proposal(bad_path)))

    message = agent.implement_step(PlanStep(step_id=1, description="add x"))

    assert message.status == MessageStatus.ERROR
    assert "policy" in message.error.lower()
    assert not (tmp_path / "test_ok.py").exists()
    assert not (tmp_path / bad_path).exists()


def test_implement_step_rejects_oversized_content_without_writing_any_file(tmp_path):
    agent = CoderAgent(
        llm_client=FakeLLMClient(text=_two_file_proposal("big.py", "x" * 500)),
        filesystem=WritableFilesystem(tmp_path, max_write_bytes=200),
        test_runner=SandboxedPytestRunner(tmp_path),
        task_id="task-1",
    )

    message = agent.implement_step(PlanStep(step_id=1, description="add x"))

    assert message.status == MessageStatus.ERROR
    assert not (tmp_path / "test_ok.py").exists()


def test_implement_step_reports_an_os_error_during_writing_instead_of_crashing(tmp_path):
    class FailingFilesystem(WritableFilesystem):
        def write_file(self, relative_path, content):
            raise OSError("disk full")

    agent = CoderAgent(
        llm_client=FakeLLMClient(text=_two_file_proposal("calc.py")),
        filesystem=FailingFilesystem(tmp_path),
        test_runner=SandboxedPytestRunner(tmp_path),
        task_id="task-1",
    )

    message = agent.implement_step(PlanStep(step_id=1, description="add x"))

    assert message.status == MessageStatus.ERROR
    assert "disk full" in message.error


_STEP = PlanStep(step_id=1, description="add add()", edge_cases=[])


def test_coder_sends_no_schema_unless_constrain_json_is_enabled(agent_factory):
    llm = FakeLLMClient(text="not json")

    agent_factory(llm).implement_step(_STEP)

    assert llm.last_json_schema is None


def test_coder_constrains_the_response_to_the_code_change_proposal_schema(agent_factory):
    from multiagent.agents.coder.schemas import CodeChangeProposal

    llm = FakeLLMClient(text="not json")

    agent_factory(llm, constrain_json=True).implement_step(_STEP)

    assert llm.last_json_schema == CodeChangeProposal.model_json_schema()


def test_the_agent_picks_the_words_prompt_only_when_it_is_constrained(agent_factory):
    plain, constrained = FakeLLMClient(text="not json"), FakeLLMClient(text="not json")

    agent_factory(plain).implement_step(_STEP)
    agent_factory(constrained, constrain_json=True).implement_step(_STEP)

    assert '"test_files": [{"path"' in plain.last_prompt
    assert '"test_files": [{"path"' not in constrained.last_prompt


def test_implement_step_puts_the_goal_in_the_prompt(agent_factory):
    llm = FakeLLMClient(text="not json")

    agent_factory(llm).implement_step(_STEP, goal="Add add(a, b) in calc.py")

    assert "Add add(a, b) in calc.py" in llm.last_prompt


def test_the_report_carries_the_content_of_every_file_written(tmp_path, agent_factory):
    test_content = "from calc import add\n\ndef test_add():\n    assert add(1, 2) == 3\n"
    impl_content = "def add(a, b):\n    return a + b\n"
    agent = agent_factory(FakeLLMClient(text=_proposal_json(test_content, impl_content)))

    message = agent.implement_step(_STEP)

    assert message.payload.file_contents == {"test_calc.py": test_content, "calc.py": impl_content}


def test_a_long_file_is_truncated_in_the_report_but_written_in_full(tmp_path):
    long_impl = "x = 1\n" * 2000  # 14,000 characters
    test_content = "from calc import x\n\ndef test_x():\n    assert x == 1\n"
    agent = CoderAgent(
        llm_client=FakeLLMClient(text=_proposal_json(test_content, long_impl)),
        filesystem=WritableFilesystem(tmp_path),
        test_runner=SandboxedPytestRunner(tmp_path),
        task_id="t",
        max_report_file_chars=500,
    )

    message = agent.implement_step(_STEP)

    shown = message.payload.file_contents["calc.py"]
    assert len(shown) < 600 and shown.endswith("[truncated]")
    assert (tmp_path / "calc.py").read_text(encoding="utf-8") == long_impl


def test_feedback_from_the_reviewer_is_put_in_the_prompt(agent_factory):
    llm = FakeLLMClient(text="not json")

    agent_factory(llm).implement_step(_STEP, feedback="The test asserts nothing about negatives.")

    assert "The test asserts nothing about negatives." in llm.last_prompt
