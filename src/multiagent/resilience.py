"""Bounded retry with an optional fallback, and a circuit breaker for repeated failures.

Per CLAUDE.md §4: every retry has a hard cap; exhausting it escalates instead of looping forever.
Generic and agent-agnostic, so any agent's LLM/tool calls can reuse the same bounded-retry
behavior instead of hand-rolling it per call site.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class RetryResult(Generic[T]):
    value: T | None
    attempts: int
    succeeded: bool
    last_error: str | None = None


def retry_with_fallback(
    operation: Callable[[], T],
    *,
    max_attempts: int,
    is_acceptable: Callable[[T], bool] = lambda _value: True,
) -> RetryResult[T]:
    """Call `operation` up to `max_attempts` times, stopping early once `is_acceptable` is True.

    An exception from `operation` counts as a failed attempt (not a crash) and is retried like
    any other unacceptable result; the caller decides what "acceptable" means for their case.
    """
    if max_attempts <= 0:
        raise ValueError("max_attempts must be positive")

    last_error: str | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            value = operation()
        except Exception as exc:  # noqa: BLE001 - any failure here is a retry-worthy attempt, not a crash
            last_error = str(exc)
            continue
        if is_acceptable(value):
            return RetryResult(value=value, attempts=attempt, succeeded=True)
        last_error = "result was not acceptable"
    return RetryResult(value=None, attempts=max_attempts, succeeded=False, last_error=last_error)


class CircuitOpenError(RuntimeError):
    """Raised when an operation is attempted while its circuit breaker is open."""


class CircuitBreaker:
    """Trips open after `failure_threshold` consecutive failures, blocking further attempts.

    A hard backstop on top of (not instead of) each individual call's own bounded retries: if an
    operation keeps failing across many separate calls, stop attempting it at all rather than
    retrying forever, one exhausted retry budget at a time.
    """

    def __init__(self, failure_threshold: int):
        if failure_threshold <= 0:
            raise ValueError("failure_threshold must be positive")
        self._failure_threshold = failure_threshold
        self._consecutive_failures = 0

    @property
    def is_open(self) -> bool:
        return self._consecutive_failures >= self._failure_threshold

    def record_success(self) -> None:
        self._consecutive_failures = 0

    def record_failure(self) -> None:
        self._consecutive_failures += 1

    def guard(self) -> None:
        """Raise CircuitOpenError if open; call before attempting the guarded operation."""
        if self.is_open:
            raise CircuitOpenError(
                f"circuit open after {self._consecutive_failures} consecutive failures"
            )
