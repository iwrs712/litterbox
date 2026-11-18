from __future__ import annotations

import logging
import os
from typing import Any

from opentelemetry import metrics as otel_metrics
from opentelemetry import trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ALWAYS_ON, ParentBased, TraceIdRatioBased
from opentelemetry.trace import Status, StatusCode

from orchestrator.config import Settings, get_settings

logger = logging.getLogger(__name__)

_configured = False
_tracer_provider: TracerProvider | None = None
_meter_provider: MeterProvider | None = None
_logger_provider: LoggerProvider | None = None
_logging_handler: LoggingHandler | None = None


def _endpoint(base: str, signal: str) -> str:
    override = os.getenv(f"OTEL_EXPORTER_OTLP_{signal.upper()}_ENDPOINT")
    if override:
        return override
    base = base.rstrip("/")
    if base.endswith(f"/v1/{signal}"):
        return base
    return f"{base}/v1/{signal}"


def _service_name(settings: Settings, role: str) -> str:
    explicit = os.getenv("OTEL_SERVICE_NAME")
    if explicit:
        return explicit
    name = settings.telemetry.service_name
    if role == "worker":
        return f"{name}-worker"
    return name


def _resource(settings: Settings, role: str) -> Resource:
    environment = settings.telemetry.environment
    attributes: dict[str, Any] = {
        "service.name": _service_name(settings, role),
        "service.namespace": settings.telemetry.service_namespace,
        "service.version": os.getenv("ORCHESTRATOR_VERSION", "1.0.0"),
        # Keep both the current and the pre-1.27 semantic-convention key so
        # SigNoz and other backends group the service the same way.
        "deployment.environment.name": environment,
        "deployment.environment": environment,
        "litterbox.component": role,
    }
    pod_name = os.getenv("HOSTNAME")
    if pod_name:
        attributes["k8s.pod.name"] = pod_name
    namespace = os.getenv("POD_NAMESPACE")
    if namespace:
        attributes["k8s.namespace.name"] = namespace
    return Resource.create(attributes)


def _disabled() -> bool:
    return os.getenv("OTEL_SDK_DISABLED", "").lower() == "true"


def configure_telemetry(
    role: str = "api",
    *,
    app: Any | None = None,
) -> None:
    """Initialize OpenTelemetry for the API or Celery worker process.

    Safe to call more than once: the SDK providers are installed only once per
    process, while a FastAPI app can be instrumented on first use.
    """
    global _configured, _tracer_provider, _meter_provider, _logger_provider
    global _logging_handler

    if _disabled():
        logger.info("OpenTelemetry disabled by OTEL_SDK_DISABLED")
        return

    settings = get_settings()
    if not settings.telemetry.enabled:
        logger.debug("OpenTelemetry not enabled in settings")
        return

    if not _configured:
        resource = _resource(settings, role)
        endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") or settings.telemetry.endpoint

        ratio = settings.telemetry.sample_ratio
        sampler = ParentBased(ALWAYS_ON if ratio >= 1.0 else TraceIdRatioBased(ratio))
        _tracer_provider = TracerProvider(resource=resource, sampler=sampler)
        _tracer_provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(endpoint=_endpoint(endpoint, "traces"), timeout=5)
            )
        )
        trace.set_tracer_provider(_tracer_provider)

        _meter_provider = MeterProvider(
            resource=resource,
            metric_readers=[
                PeriodicExportingMetricReader(
                    OTLPMetricExporter(endpoint=_endpoint(endpoint, "metrics"), timeout=5),
                    export_interval_millis=int(
                        settings.telemetry.export_interval_seconds * 1000
                    ),
                )
            ],
        )
        otel_metrics.set_meter_provider(_meter_provider)

        _logger_provider = LoggerProvider(resource=resource)
        _logger_provider.add_log_record_processor(
            BatchLogRecordProcessor(
                OTLPLogExporter(endpoint=_endpoint(endpoint, "logs"), timeout=5)
            )
        )
        set_logger_provider(_logger_provider)

        root = logging.getLogger()
        root.setLevel(settings.telemetry.log_level.upper())
        _logging_handler = LoggingHandler(level=logging.NOTSET, logger_provider=_logger_provider)
        root.addHandler(_logging_handler)
        # Uvicorn and Celery install their own console handlers with
        # propagate=False. Let their records reach the OTel handler on root;
        # root has no console handler, so console output is unchanged.
        for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "celery"):
            logging.getLogger(name).propagate = True

        HTTPXClientInstrumentor().instrument()

        if role == "worker":
            from opentelemetry.instrumentation.celery import CeleryInstrumentor

            CeleryInstrumentor().instrument()

        _configured = True
        logger.info(
            "OpenTelemetry enabled role=%s service=%s endpoint=%s",
            role,
            _service_name(settings, role),
            endpoint,
        )

    if app is not None:
        FastAPIInstrumentor.instrument_app(
            app,
            excluded_urls=settings.telemetry.excluded_urls,
        )


def shutdown_telemetry() -> None:
    """Flush pending telemetry; called when the API or worker exits."""
    global _tracer_provider, _meter_provider, _logger_provider
    for provider in (_tracer_provider, _meter_provider, _logger_provider):
        if provider is None:
            continue
        try:
            provider.shutdown()
        except Exception:  # noqa: BLE001
            logger.debug("telemetry provider shutdown failed", exc_info=True)
    _tracer_provider = None
    _meter_provider = None
    _logger_provider = None


def annotate_current_span(**attributes: Any) -> None:
    span = trace.get_current_span()
    if not span.is_recording():
        return
    for key, value in attributes.items():
        if value is not None:
            span.set_attribute(key, value)


def record_span_exception(span: trace.Span, exc: BaseException) -> None:
    span.record_exception(exc)
    span.set_attribute("error.type", type(exc).__name__)
    span.set_status(Status(StatusCode.ERROR, type(exc).__name__))


def normalize_envd_path(path: str) -> str:
    """Bound envd path cardinality while keeping the RPC/service visible.

    ``process.Process/Start`` -> ``process.Process/Start``
    ``v1/workspace/restore``  -> ``v1/workspace``
    ``health``                -> ``health``
    """
    parts = [part for part in (path or "").split("/") if part]
    if not parts:
        return "root"
    return "/".join(parts[:2])
