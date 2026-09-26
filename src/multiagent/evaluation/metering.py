"""Wrappers that observe a run without changing it.

The agents take their LLM client and tools by injection, so metering is done by wrapping those
objects: no agent code changes, and the same wrappers work against fakes in tests and against the
real models in an actual evaluation. Everything is recorded on a `Meter`, one per run.

Recorded at three levels, because each answers a different question: LLM calls (tokens and
latency — only the client sees these), agent calls (outcome: ok/error/needs-clarification, and
whether the Coder's tests passed — this is what "retry" and "recovery" are computed from), and tool
calls (whether each real git operation succeeded).
"""

import time
from dataclasses import dataclass, field
from typing import Any

from multiagent.llm.base import LLMClient, LLMResponse


@dataclass(frozen=True)
class LLMCall:
    role: str
    prompt_tokens: int
    completion_tokens: int
    latency_seconds: float
    error: str | None = None


@dataclass(frozen=True)
class AgentCall:
    agent: str
    method: str
    status: str
    error: str | None
    tests_passed: bool | None
    duration_seconds: float


@dataclass(frozen=True)
class ToolCall:
    operation: str
    success: bool
    timed_out: bool
    duration_seconds: float


@dataclass
class Meter:
    llm_calls: list[LLMCall] = field(default_factory=list)
    agent_calls: list[AgentCall] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)

    def total_tokens(self, role: str | None = None) -> int:
        return sum(
            call.prompt_tokens + call.completion_tokens
            for call in self.llm_calls
            if role is None or call.role == role
        )

    def llm_seconds(self) -> float:
        return sum(call.latency_seconds for call in self.llm_calls)


class MeteredLLMClient:
    """An LLMClient that records every call (and every failure) on the meter."""

    def __init__(self, inner: LLMClient, meter: Meter, role: str):
        self._inner = inner
        self._meter = meter
        self._role = role

    def generate(self, prompt: str, *, max_tokens: int = 512) -> LLMResponse:
        started = time.monotonic()
        try:
            response = self._inner.generate(prompt, max_tokens=max_tokens)
        except Exception as exc:
            self._meter.llm_calls.append(
                LLMCall(self._role, 0, 0, time.monotonic() - started, error=str(exc))
            )
            raise
        self._meter.llm_calls.append(
            LLMCall(
                self._role,
                response.prompt_tokens,
                response.completion_tokens,
                response.latency_seconds,
            )
        )
        return response


class MeteredAgent:
    """Wraps a Planner/Coder/Tool agent; records the outcome of each AgentMessage it returns."""

    def __init__(self, inner: Any, meter: Meter, name: str):
        self._inner = inner
        self._meter = meter
        self._name = name

    def __getattr__(self, attribute: str) -> Any:
        target = getattr(self._inner, attribute)
        if not callable(target):
            return target

        def call(*args: Any, **kwargs: Any) -> Any:
            started = time.monotonic()
            try:
                message = target(*args, **kwargs)
            except Exception as exc:
                self._meter.agent_calls.append(
                    AgentCall(self._name, attribute, "exception", str(exc), None, time.monotonic() - started)
                )
                raise
            self._meter.agent_calls.append(
                AgentCall(
                    self._name,
                    attribute,
                    message.status.value,
                    message.error,
                    getattr(message.payload, "tests_passed", None),
                    time.monotonic() - started,
                )
            )
            return message

        return call


class MeteredTools:
    """Wraps a tool object (e.g. GitTools); records each operation's success and timeout."""

    def __init__(self, inner: Any, meter: Meter):
        self._inner = inner
        self._meter = meter

    def __getattr__(self, operation: str) -> Any:
        target = getattr(self._inner, operation)
        if not callable(target):
            return target

        def call(*args: Any, **kwargs: Any) -> Any:
            started = time.monotonic()
            try:
                result = target(*args, **kwargs)
            except Exception:
                self._meter.tool_calls.append(
                    ToolCall(operation, False, False, time.monotonic() - started)
                )
                raise
            self._meter.tool_calls.append(
                ToolCall(
                    operation,
                    result.success,
                    getattr(result, "timed_out", False),
                    time.monotonic() - started,
                )
            )
            return result

        return call
