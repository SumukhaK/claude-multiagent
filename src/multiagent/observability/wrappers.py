"""Wrappers that trace every LLM, agent and tool call without changing the wrapped objects.

Same idea as the metering wrappers in `multiagent.evaluation.metering`: the agents take their LLM
client and tools by injection, so tracing is done by wrapping those objects and no agent code
changes. Spans nest on their own (an LLM call made inside an agent call becomes its child).

Two rules worth knowing:
- Agents report failure by *returning* an AgentMessage with status "error", not by raising, so an
  error-status message is treated as a failure here (span marked ERROR, failure log entry) exactly
  like an exception. A clarification request is not a failure.
- Prompts, responses and raw tool output are never recorded: they can contain the user's code or
  secrets. Only metadata (names, sizes, token counts, statuses, error text) goes on spans.
"""

from typing import Any

from opentelemetry.trace import Span, Status, StatusCode, Tracer

from multiagent.llm.base import LLMClient, LLMResponse
from multiagent.observability.tracing import FailureLog, traced_call, truncate_error


def _fail(span: Span, failure_log: FailureLog | None, name: str, error: str, attributes: dict) -> None:
    """Record a failure that came back as a return value rather than as an exception."""
    span.set_status(Status(StatusCode.ERROR, truncate_error(error)))
    if failure_log is not None:
        failure_log.record(call_name=name, error=error, attributes=attributes)


class TracedLLMClient:
    """An LLMClient that traces every call (role, sizes and token counts; never the prompt)."""

    def __init__(self, inner: LLMClient, tracer: Tracer, role: str, failure_log: FailureLog | None = None):
        self._inner = inner
        self._tracer = tracer
        self._role = role
        self._failure_log = failure_log

    def generate(
        self, prompt: str, *, max_tokens: int = 512, json_schema: dict | None = None
    ) -> LLMResponse:
        extra = {} if json_schema is None else {"json_schema": json_schema}
        attributes = {"role": self._role, "max_tokens": max_tokens, "json_constrained": json_schema is not None}
        with traced_call(self._tracer, f"llm.{self._role}.generate", self._failure_log, **attributes) as span:
            response = self._inner.generate(prompt, max_tokens=max_tokens, **extra)
            span.set_attribute("prompt_tokens", response.prompt_tokens)
            span.set_attribute("completion_tokens", response.completion_tokens)
            return response


class TracedAgent:
    """Wraps a Planner/Coder/Tool agent; traces each method call and its AgentMessage status."""

    def __init__(self, inner: Any, tracer: Tracer, name: str, failure_log: FailureLog | None = None):
        self._inner = inner
        self._tracer = tracer
        self._name = name
        self._failure_log = failure_log

    def __getattr__(self, attribute: str) -> Any:
        target = getattr(self._inner, attribute)
        if not callable(target):
            return target

        def call(*args: Any, **kwargs: Any) -> Any:
            name = f"agent.{self._name}.{attribute}"
            with traced_call(self._tracer, name, self._failure_log, agent=self._name) as span:
                message = target(*args, **kwargs)
                span.set_attribute("status", message.status.value)
                if message.error is not None:
                    _fail(span, self._failure_log, name, message.error, {"agent": self._name})
                return message

        return call


class TracedTools:
    """Wraps a tool object (e.g. GitTools); traces each operation. An unsuccessful result is a
    failure, recorded by return code and timeout flag only (raw output can hold remote URLs)."""

    def __init__(self, inner: Any, tracer: Tracer, failure_log: FailureLog | None = None):
        self._inner = inner
        self._tracer = tracer
        self._failure_log = failure_log

    def __getattr__(self, operation: str) -> Any:
        target = getattr(self._inner, operation)
        if not callable(target):
            return target

        def call(*args: Any, **kwargs: Any) -> Any:
            name = f"tool.{operation}"
            with traced_call(self._tracer, name, self._failure_log, operation=operation) as span:
                result = target(*args, **kwargs)
                timed_out = getattr(result, "timed_out", False)
                span.set_attribute("success", result.success)
                span.set_attribute("timed_out", timed_out)
                if not result.success:
                    _fail(
                        span,
                        self._failure_log,
                        name,
                        f"exit code {getattr(result, 'return_code', 'unknown')}",
                        {"operation": operation, "timed_out": timed_out},
                    )
                return result

        return call
