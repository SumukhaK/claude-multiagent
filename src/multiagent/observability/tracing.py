"""OpenTelemetry tracing for every agent/tool call, plus a dedicated failure log.

Per CLAUDE.md §4: every agent and tool call is logged and traced, and failures are recorded to a
dedicated failure log, so runs can be evaluated after the fact. Tracing is local-only for now
(console exporter) — no cloud account needed, matching the "free tier only" project constraint.
"""

import json
import time
from contextlib import contextmanager
from pathlib import Path

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
from opentelemetry.trace import Tracer

from config.settings import Settings

_configured = False


def configure_tracing(settings: Settings, _force: bool = False) -> None:
    """Set the global TracerProvider once, honoring settings.otel_enabled.

    `_force` bypasses the once-only guard; it exists for tests, which need a fresh provider per
    test rather than sharing process-wide state.
    """
    global _configured
    if (_configured and not _force) or not settings.otel_enabled:
        return
    provider = TracerProvider(resource=Resource.create({"service.name": "multiagent"}))
    if settings.otel_exporter == "console":
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)
    _configured = True


def get_tracer() -> Tracer:
    """Return the globally configured tracer for application code to use."""
    return trace.get_tracer("multiagent")


class FailureLog:
    """Appends one structured JSON line per failed agent/tool call, for later evaluation."""

    def __init__(self, path: Path):
        self._path = path

    def record(self, *, call_name: str, error: str, attributes: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": time.time(),
            "call": call_name,
            "error": error,
            "attributes": attributes,
        }
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")


@contextmanager
def traced_call(tracer: Tracer, name: str, failure_log: FailureLog | None = None, **attributes):
    """Wrap one agent/tool call in a span; on exception, log it and reraise.

    `start_as_current_span` already records the exception on the span and sets its status to
    ERROR by default once the exception propagates past this function, so this only needs to
    handle the failure log before reraising.
    """
    with tracer.start_as_current_span(name, attributes=attributes) as span:
        try:
            yield span
        except Exception as exc:
            if failure_log is not None:
                failure_log.record(call_name=name, error=str(exc), attributes=attributes)
            raise
