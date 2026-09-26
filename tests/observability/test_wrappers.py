"""Tests for the tracing wrappers: every LLM, agent and tool call becomes a span, and every failure
(an exception, an error-status AgentMessage, an unsuccessful tool result) lands in the failure log.

The wrappers are used the same way as the metering ones: they wrap the injected objects, so no
agent code changes.
"""

import json
from types import SimpleNamespace

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from multiagent.contracts.messages import AgentMessage, AgentName, MessageStatus
from multiagent.llm.base import LLMResponse
from multiagent.observability.tracing import FailureLog
from multiagent.observability.wrappers import TracedAgent, TracedLLMClient, TracedTools


@pytest.fixture
def tracing(tmp_path):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    log_path = tmp_path / "failures.jsonl"
    return SimpleNamespace(
        tracer=provider.get_tracer("test"),
        exporter=exporter,
        failure_log=FailureLog(log_path),
        failures=lambda: [json.loads(line) for line in log_path.read_text().splitlines()]
        if log_path.exists()
        else [],
    )


class FakeLLM:
    def __init__(self, error: Exception | None = None):
        self._error = error
        self.kwargs = None

    def generate(self, prompt, **kwargs):
        self.kwargs = kwargs
        if self._error:
            raise self._error
        return LLMResponse(text="reply", prompt_tokens=30, completion_tokens=12, latency_seconds=0.5)


def _message(status: MessageStatus, error: str | None = None) -> AgentMessage:
    return AgentMessage(agent=AgentName.PLANNER, task_id="t", status=status, error=error)


class FakeAgent:
    def __init__(self, message=None, error: Exception | None = None):
        self._message = message
        self._error = error
        self.label = "not callable"

    def create_plan(self, goal):
        if self._error:
            raise self._error
        return self._message


def test_llm_call_becomes_a_span_with_token_counts_and_no_prompt_text(tracing):
    llm = TracedLLMClient(FakeLLM(), tracing.tracer, "planner", tracing.failure_log)

    result = llm.generate("SECRET-LOOKING PROMPT BODY", max_tokens=64)

    assert result.text == "reply"
    span = tracing.exporter.get_finished_spans()[0]
    assert span.name == "llm.planner.generate"
    assert span.attributes["role"] == "planner"
    assert span.attributes["max_tokens"] == 64
    assert span.attributes["json_constrained"] is False
    assert (span.attributes["prompt_tokens"], span.attributes["completion_tokens"]) == (30, 12)
    assert "SECRET-LOOKING" not in json.dumps(dict(span.attributes))


def test_llm_call_forwards_a_json_schema_only_when_given_and_flags_it(tracing):
    inner = FakeLLM()
    llm = TracedLLMClient(inner, tracing.tracer, "coder", tracing.failure_log)

    llm.generate("p", max_tokens=8)
    assert inner.kwargs == {"max_tokens": 8}
    llm.generate("p", max_tokens=8, json_schema={"type": "object"})

    assert inner.kwargs == {"max_tokens": 8, "json_schema": {"type": "object"}}
    assert tracing.exporter.get_finished_spans()[1].attributes["json_constrained"] is True


def test_llm_exception_marks_the_span_and_writes_the_failure_log_then_reraises(tracing):
    llm = TracedLLMClient(FakeLLM(ConnectionError("down")), tracing.tracer, "planner", tracing.failure_log)

    with pytest.raises(ConnectionError):
        llm.generate("p")

    assert tracing.exporter.get_finished_spans()[0].status.status_code == StatusCode.ERROR
    assert tracing.failures()[0]["call"] == "llm.planner.generate"
    assert tracing.failures()[0]["error"] == "down"


def test_agent_call_becomes_a_span_with_the_message_status(tracing):
    agent = TracedAgent(FakeAgent(_message(MessageStatus.OK)), tracing.tracer, "planner", tracing.failure_log)

    agent.create_plan("g")

    span = tracing.exporter.get_finished_spans()[0]
    assert span.name == "agent.planner.create_plan"
    assert span.attributes["status"] == "ok"
    assert span.status.status_code != StatusCode.ERROR
    assert tracing.failures() == []


def test_an_error_status_message_is_a_failure_even_though_nothing_was_raised(tracing):
    """Agents report failure by returning status=error, not by raising: the common failure path."""
    agent = TracedAgent(
        FakeAgent(_message(MessageStatus.ERROR, "no complete JSON object")),
        tracing.tracer,
        "planner",
        tracing.failure_log,
    )

    message = agent.create_plan("g")

    assert message.status == MessageStatus.ERROR  # returned unchanged
    assert tracing.exporter.get_finished_spans()[0].status.status_code == StatusCode.ERROR
    assert tracing.failures()[0]["call"] == "agent.planner.create_plan"
    assert tracing.failures()[0]["error"] == "no complete JSON object"


def test_a_clarification_request_is_not_a_failure(tracing):
    agent = TracedAgent(
        FakeAgent(_message(MessageStatus.NEEDS_CLARIFICATION)), tracing.tracer, "planner", tracing.failure_log
    )

    agent.create_plan("g")

    assert tracing.failures() == []


def test_an_agent_exception_is_logged_and_reraised(tracing):
    agent = TracedAgent(FakeAgent(error=RuntimeError("boom")), tracing.tracer, "coder", tracing.failure_log)

    with pytest.raises(RuntimeError):
        agent.create_plan("g")

    assert tracing.failures()[0]["error"] == "boom"


def test_non_callable_attributes_pass_through_untraced(tracing):
    agent = TracedAgent(FakeAgent(), tracing.tracer, "planner", tracing.failure_log)

    assert agent.label == "not callable"
    assert tracing.exporter.get_finished_spans() == ()


def test_llm_spans_are_children_of_the_agent_span_that_caused_them(tracing):
    llm = TracedLLMClient(FakeLLM(), tracing.tracer, "planner", tracing.failure_log)

    class LLMUsingAgent:
        def create_plan(self, goal):
            llm.generate("p")
            return _message(MessageStatus.OK)

    TracedAgent(LLMUsingAgent(), tracing.tracer, "planner", tracing.failure_log).create_plan("g")

    llm_span, agent_span = tracing.exporter.get_finished_spans()
    assert llm_span.context.trace_id == agent_span.context.trace_id
    assert llm_span.parent.span_id == agent_span.context.span_id


class FakeTools:
    def __init__(self, success: bool, timed_out: bool = False):
        self._result = SimpleNamespace(success=success, timed_out=timed_out, return_code=1, output="details")

    def commit(self, message):
        return self._result


def test_a_successful_tool_call_is_a_span_and_not_a_failure(tracing):
    tools = TracedTools(FakeTools(True), tracing.tracer, tracing.failure_log)

    tools.commit("m")

    span = tracing.exporter.get_finished_spans()[0]
    assert span.name == "tool.commit"
    assert span.attributes["success"] is True
    assert tracing.failures() == []


def test_an_unsuccessful_tool_result_is_a_failure_with_its_timeout_flag(tracing):
    tools = TracedTools(FakeTools(False, timed_out=True), tracing.tracer, tracing.failure_log)

    result = tools.commit("m")

    assert result.success is False  # returned unchanged
    assert tracing.exporter.get_finished_spans()[0].status.status_code == StatusCode.ERROR
    failure = tracing.failures()[0]
    assert failure["call"] == "tool.commit"
    assert failure["attributes"]["timed_out"] is True


def test_long_error_text_is_truncated_because_validation_errors_can_quote_model_output(tracing):
    """Pydantic errors embed input_value=...; cap what a failure-log entry can carry of it."""
    quoted_model_output = "x" * 5000
    agent = TracedAgent(
        FakeAgent(_message(MessageStatus.ERROR, quoted_model_output)), tracing.tracer, "coder", tracing.failure_log
    )

    agent.create_plan("g")

    logged = tracing.failures()[0]["error"]
    assert len(logged) < 500
    assert logged.endswith("...[truncated]")
