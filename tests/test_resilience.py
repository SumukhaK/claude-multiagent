"""Tests for the shared bounded-retry and circuit-breaker primitives.

Per CLAUDE.md §4: every retry has a hard cap, and exhausting it escalates rather than looping
forever. These are generic (no dependency on git, LLM clients, or any specific agent) so any
agent's orchestration can reuse them rather than hand-rolling retry logic per call site.
"""

import pytest

from multiagent.resilience import CircuitBreaker, CircuitOpenError, retry_with_fallback


def test_retry_succeeds_on_the_first_attempt():
    result = retry_with_fallback(lambda: "ok", max_attempts=3)

    assert result.succeeded is True
    assert result.value == "ok"
    assert result.attempts == 1


def test_retry_recovers_after_an_exception():
    calls = {"count": 0}

    def flaky():
        calls["count"] += 1
        if calls["count"] < 2:
            raise RuntimeError("transient failure")
        return "ok"

    result = retry_with_fallback(flaky, max_attempts=3)

    assert result.succeeded is True
    assert result.value == "ok"
    assert result.attempts == 2


def test_retry_recovers_after_an_unacceptable_result():
    calls = {"count": 0}

    def sometimes_empty():
        calls["count"] += 1
        return "" if calls["count"] < 2 else "real answer"

    result = retry_with_fallback(sometimes_empty, max_attempts=3, is_acceptable=bool)

    assert result.succeeded is True
    assert result.value == "real answer"
    assert result.attempts == 2


def test_retry_exhausts_attempts_and_reports_the_last_error():
    def always_fails():
        raise RuntimeError("still broken")

    result = retry_with_fallback(always_fails, max_attempts=3)

    assert result.succeeded is False
    assert result.value is None
    assert result.attempts == 3
    assert "still broken" in result.last_error


def test_retry_exhausts_attempts_when_result_is_never_acceptable():
    result = retry_with_fallback(lambda: "", max_attempts=2, is_acceptable=bool)

    assert result.succeeded is False
    assert result.attempts == 2


def test_retry_rejects_a_non_positive_max_attempts():
    with pytest.raises(ValueError):
        retry_with_fallback(lambda: "ok", max_attempts=0)


def test_circuit_breaker_starts_closed():
    breaker = CircuitBreaker(failure_threshold=2)

    assert breaker.is_open is False
    breaker.guard()  # must not raise


def test_circuit_breaker_opens_after_the_failure_threshold():
    breaker = CircuitBreaker(failure_threshold=2)

    breaker.record_failure()
    assert breaker.is_open is False
    breaker.record_failure()
    assert breaker.is_open is True

    with pytest.raises(CircuitOpenError):
        breaker.guard()


def test_circuit_breaker_success_resets_the_failure_count():
    breaker = CircuitBreaker(failure_threshold=2)

    breaker.record_failure()
    breaker.record_success()
    breaker.record_failure()

    assert breaker.is_open is False


def test_circuit_breaker_rejects_a_non_positive_threshold():
    with pytest.raises(ValueError):
        CircuitBreaker(failure_threshold=0)
