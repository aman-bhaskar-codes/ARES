from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest
from ares.application.observability import optional_span


class _BrokenExitSpan:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        raise RuntimeError("exporter broke while closing span")


class _Tracer:
    def start_as_current_span(self, *args, **kwargs):
        return _BrokenExitSpan()


def test_optional_span_never_turns_exporter_failure_into_application_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_trace = SimpleNamespace(get_tracer=lambda name: _Tracer())
    fake_package = SimpleNamespace(trace=fake_trace)
    monkeypatch.setitem(sys.modules, "opentelemetry", fake_package)

    with optional_span("stage", run_id="abc"):
        value = 42
    assert value == 42


def test_optional_span_preserves_application_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_trace = SimpleNamespace(get_tracer=lambda name: _Tracer())
    fake_package = SimpleNamespace(trace=fake_trace)
    monkeypatch.setitem(sys.modules, "opentelemetry", fake_package)

    with pytest.raises(ValueError, match="application failure"):
        with optional_span("stage"):
            raise ValueError("application failure")


def test_telemetry_export_status_distinguishes_configured_from_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ares.application import observability

    assert observability.telemetry_export_status("") == {
        "configured": False,
        "ready": False,
        "degraded": False,
    }
    monkeypatch.setattr(observability.importlib.util, "find_spec", lambda name: None)
    assert observability.telemetry_export_status("https://otel.example") == {
        "configured": True,
        "ready": False,
        "degraded": True,
    }


def test_configure_llm_tracing(monkeypatch: pytest.MonkeyPatch) -> None:
    from collections.abc import Callable
    from typing import Any

    from ares.application import observability

    calls: list[dict[str, Any]] = []

    def mock_configure_telemetry(**kwargs: Any) -> Callable[[], None]:
        calls.append(kwargs)
        return lambda: None

    monkeypatch.setattr(observability, "configure_telemetry", mock_configure_telemetry)

    # Test phoenix endpoint
    observability.configure_llm_tracing(phoenix_endpoint="http://localhost:6006/v1/traces")
    assert len(calls) == 1
    assert calls[0]["endpoint"] == "http://localhost:6006/v1/traces"

    # Test langfuse host
    observability.configure_llm_tracing(langfuse_host="https://cloud.langfuse.com")
    assert len(calls) == 2
    assert calls[1]["endpoint"] == "https://cloud.langfuse.com/api/public/otel"

