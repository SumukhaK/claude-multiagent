"""Tests for the OpenTelemetry tracing wrapper and its dedicated failure log.

Every agent/tool call must be traced and, on failure, recorded to a structured failure log for
later evaluation (CLAUDE.md §4 / REQUIREMENTS.md §1 item 7).
"""

import json

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from config.settings import Settings
from multiagent.observability.tracing import FailureLog, configure_tracing, traced_call


@pytest.fixture
def tracer_and_exporter():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider.get_tracer("test"), exporter


def test_traced_call_records_a_successful_span(tracer_and_exporter):
    tracer, exporter = tracer_and_exporter

    with traced_call(tracer, "planner.plan", task_id="t1"):
        pass

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "planner.plan"
    assert spans[0].attributes["task_id"] == "t1"
    assert spans[0].status.status_code != StatusCode.ERROR


def test_traced_call_marks_span_as_error_and_reraises_on_exception(tracer_and_exporter):
    tracer, exporter = tracer_and_exporter

    with pytest.raises(ValueError), traced_call(tracer, "coder.write_test"):
        raise ValueError("boom")

    spans = exporter.get_finished_spans()
    assert spans[0].status.status_code == StatusCode.ERROR
    assert len(spans[0].events) == 1  # the recorded exception


def test_traced_call_writes_to_failure_log_only_on_error(tracer_and_exporter, tmp_path):
    tracer, _exporter = tracer_and_exporter
    failure_log = FailureLog(tmp_path / "failures.jsonl")

    with traced_call(tracer, "planner.plan", failure_log=failure_log, task_id="t1"):
        pass

    assert not (tmp_path / "failures.jsonl").exists()

    with pytest.raises(RuntimeError), traced_call(
        tracer, "coder.run_tests", failure_log=failure_log, step_id=2
    ):
        raise RuntimeError("tests failed")

    lines = (tmp_path / "failures.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["call"] == "coder.run_tests"
    assert entry["error"] == "tests failed"
    assert entry["attributes"] == {"step_id": 2}


def test_failure_log_creates_its_parent_directory_if_missing(tmp_path):
    log_path = tmp_path / "nested" / "dir" / "failures.jsonl"
    failure_log = FailureLog(log_path)

    failure_log.record(call_name="x", error="y", attributes={})

    assert log_path.exists()


def test_configure_tracing_sets_a_provider_when_enabled(monkeypatch):
    captured = {}
    monkeypatch.setattr(trace, "set_tracer_provider", lambda provider: captured.setdefault("provider", provider))

    settings = Settings(_env_file=None, otel_enabled=True, otel_exporter="console")
    configure_tracing(settings, _force=True)

    assert "provider" in captured


def test_configure_tracing_does_nothing_when_disabled(monkeypatch):
    called = {"count": 0}
    monkeypatch.setattr(trace, "set_tracer_provider", lambda provider: called.__setitem__("count", called["count"] + 1))

    settings = Settings(_env_file=None, otel_enabled=False)
    configure_tracing(settings, _force=True)

    assert called["count"] == 0


def test_configure_tracing_file_exporter_writes_one_json_span_per_line(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(trace, "set_tracer_provider", lambda provider: captured.setdefault("provider", provider))
    trace_path = tmp_path / "logs" / "traces.jsonl"

    settings = Settings(_env_file=None, otel_enabled=True, otel_exporter="file", otel_trace_path=str(trace_path))
    configure_tracing(settings, _force=True)
    with captured["provider"].get_tracer("t").start_as_current_span("agent.planner.create_plan"):
        pass
    captured["provider"].force_flush()

    lines = trace_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["name"] == "agent.planner.create_plan"
