from __future__ import annotations

import contextvars
import importlib.util
import json
import logging
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Iterator

from ares.application.repository import JobLease, Repository

_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("ares_request_id", default=None)


class JsonFormatter(logging.Formatter):
    """Small bounded-cardinality JSON formatter with no secret/body logging."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = _request_id.get()
        if request_id:
            payload["request_id"] = request_id
        event = getattr(record, "event", None)
        if isinstance(event, str):
            payload["event"] = event
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            # Call sites are responsible for bounded keys/values. Never put prompts, evidence text,
            # credentials, headers, or response bodies in this structure.
            payload.update(fields)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging(*, json_logs: bool = True, level: int = logging.INFO) -> None:
    root = logging.getLogger()
    root.setLevel(level)
    if getattr(root, "_ares_configured", False):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter() if json_logs else logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root.handlers.clear()
    root.addHandler(handler)
    setattr(root, "_ares_configured", True)


@contextmanager
def request_context(request_id: str) -> Iterator[None]:
    token = _request_id.set(request_id)
    try:
        yield
    finally:
        _request_id.reset(token)


@contextmanager
def optional_span(name: str, **attributes: object) -> Iterator[None]:
    """Emit an OpenTelemetry span when available without making tracing authoritative.

    Import/start/end failures are swallowed, while exceptions raised by the wrapped application
    operation are always preserved. This keeps telemetry a bounded failure domain.
    """
    try:
        from opentelemetry import trace  # type: ignore[import-not-found]

        tracer = trace.get_tracer("ares")
        safe_attributes = {
            key: value
            for key, value in attributes.items()
            if isinstance(value, (str, bool, int, float))
        }
        span_context = tracer.start_as_current_span(name, attributes=safe_attributes)
        span_context.__enter__()
    except Exception:
        yield
        return

    try:
        yield
    except BaseException as exc:
        try:
            span_context.__exit__(type(exc), exc, exc.__traceback__)
        except Exception:
            pass
        raise
    else:
        try:
            span_context.__exit__(None, None, None)
        except Exception:
            pass


class RunTelemetry:
    """Run-local timing/event helper that cannot make research fail if telemetry fails."""

    def __init__(self, repository: Repository, lease: JobLease):
        self.repository = repository
        self.lease = lease
        self.logger = logging.getLogger("ares.run")

    @contextmanager
    def stage(self, name: str, **dimensions: object) -> Iterator[None]:
        started = time.perf_counter()
        outcome = "ok"
        try:
            with optional_span(f"ares.run.{name}", run_id=str(self.lease.run_id), stage=name):
                yield
        except Exception:
            outcome = "error"
            raise
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 3)
            payload: dict[str, object] = {
                "stage": name,
                "duration_ms": duration_ms,
                "outcome": outcome,
                **dimensions,
            }
            try:
                self.repository.record_event(
                    self.lease.run_id,
                    "stage.timing",
                    payload,
                    lease_token=self.lease.token,
                )
            except Exception:
                self.logger.warning(
                    "failed to persist run timing",
                    extra={
                        "event": "telemetry.persist_failed",
                        "fields": {"run_id": str(self.lease.run_id), "stage": name},
                    },
                    exc_info=True,
                )
            self.logger.info(
                "run stage timing",
                extra={
                    "event": "run.stage",
                    "fields": {
                        "run_id": str(self.lease.run_id),
                        "stage": name,
                        "duration_ms": duration_ms,
                        "outcome": outcome,
                    },
                },
            )


def telemetry_export_status(endpoint: str) -> dict[str, bool]:
    """Report configured/ready/degraded state without importing optional exporters."""
    configured = bool(endpoint.strip())
    if not configured:
        return {"configured": False, "ready": False, "degraded": False}
    try:
        ready = (
            importlib.util.find_spec("opentelemetry.sdk") is not None
            and importlib.util.find_spec("opentelemetry.exporter.otlp.proto.http.trace_exporter") is not None
        )
    except (ImportError, ModuleNotFoundError, ValueError):
        ready = False
    return {"configured": True, "ready": ready, "degraded": not ready}


def configure_telemetry(*, endpoint: str, service_name: str, sample_ratio: float, export_timeout_seconds: float):
    """Configure a bounded OTLP/HTTP trace exporter; returns an idempotent shutdown callable.

    Empty endpoint keeps tracing local/no-op. Export failure is intentionally not allowed to
    block request or worker correctness.
    """
    if not endpoint:
        return lambda: None
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

        current = trace.get_tracer_provider()
        if isinstance(current, TracerProvider):
            return lambda: None
        provider = TracerProvider(
            resource=Resource.create({"service.name": service_name}),
            sampler=ParentBased(TraceIdRatioBased(sample_ratio)),
        )
        exporter = OTLPSpanExporter(
            endpoint=endpoint.rstrip("/") + "/v1/traces",
            timeout=export_timeout_seconds,
        )
        processor = BatchSpanProcessor(
            exporter,
            max_queue_size=2048,
            max_export_batch_size=256,
            schedule_delay_millis=5000,
            export_timeout_millis=int(export_timeout_seconds * 1000),
        )
        provider.add_span_processor(processor)
        trace.set_tracer_provider(provider)
        return provider.shutdown
    except Exception:
        logging.getLogger("ares.telemetry").exception("OpenTelemetry exporter initialization failed; continuing without export")
        return lambda: None
