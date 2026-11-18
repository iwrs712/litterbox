from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from orchestrator.config import Settings
from orchestrator.domain.models import Template
from orchestrator.services.metrics import reset_otel_instruments, sandbox_metrics
from orchestrator.services.sandboxes import SandboxService
from orchestrator.telemetry import normalize_envd_path
from orchestrator.utils import utcnow


def template() -> Template:
    now = utcnow()
    return Template(
        id="ubuntu",
        name="ubuntu",
        image="ubuntu:24.04",
        command="sleep infinity",
        env=[],
        cpu_millicores=500,
        memory_mb=512,
        ttl_seconds=600,
        created_at=now,
        updated_at=now,
    )


class FakeCRD:
    def __init__(self) -> None:
        self.created: dict | None = None
        self.resumed: list[tuple[str, int]] = []
        self.deleted: list[str] = []

    def create(self, **kwargs) -> None:
        self.created = kwargs

    def wait_until_running(self, sandbox_id: str) -> None:
        pass

    def delete(self, sandbox_id: str) -> None:
        self.deleted.append(sandbox_id)

    def get_cr(self, sandbox_id: str) -> dict:
        return {
            "metadata": {
                "labels": {"litterbox.io/template-id": "ubuntu"},
                "annotations": {},
            },
            "spec": {"ttlSeconds": 600},
        }

    def resume(self, sandbox_id: str, *, ttl_seconds: int) -> None:
        self.resumed.append((sandbox_id, ttl_seconds))

    def suspend(self, sandbox_id: str, *, ttl_expired: bool = False) -> None:
        pass

    def wait_until_paused(self, sandbox_id: str) -> None:
        pass


def service() -> SandboxService:
    gateway = MagicMock()
    gateway.namespace = "default"
    template_service = MagicMock()
    template_service.get_template.return_value = template()
    svc = SandboxService(gateway, template_service, MagicMock(), Settings())
    svc.crd = FakeCRD()
    svc.get_sandbox = lambda sandbox_id: SimpleNamespace(  # type: ignore[method-assign]
        id=sandbox_id, template_id="ubuntu"
    )
    return svc


def traced_service() -> tuple[SandboxService, InMemorySpanExporter, TracerProvider]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("test")
    patcher = patch(
        "orchestrator.services.sandboxes.trace.get_tracer", return_value=tracer
    )
    patcher.start()
    return service(), exporter, provider


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("", "root"),
        ("/", "root"),
        ("health", "health"),
        ("process.Process/Start", "process.Process/Start"),
        ("v1/workspace/restore", "v1/workspace"),
    ],
)
def test_normalize_envd_path(path: str, expected: str) -> None:
    assert normalize_envd_path(path) == expected


def test_create_sandbox_emits_spans() -> None:
    svc, exporter, provider = traced_service()
    try:
        svc.create_sandbox(template_id="ubuntu", wait_ready=True, dispatch_events=False)

        spans = {span.name: span for span in exporter.get_finished_spans()}
        assert {
            "sandbox.create",
            "sandbox.create.claim",
            "sandbox.wait_pod_ready",
            "sandbox.wait_running_status",
        } <= spans.keys()

        create = spans["sandbox.create"]
        assert create.attributes["litterbox.template.id"] == "ubuntu"
        assert create.attributes["litterbox.outcome"] == "success"
        assert create.attributes["litterbox.sandbox.id"]
        assert create.status.status_code is StatusCode.UNSET

        wait = spans["sandbox.wait_pod_ready"]
        assert wait.parent is not None
        assert wait.parent.span_id == create.context.span_id
    finally:
        patch.stopall()
        provider.shutdown()


def test_resume_failure_marks_span_error() -> None:
    svc, exporter, provider = traced_service()
    try:
        svc.gateway.wait_for_pod_ready.side_effect = TimeoutError("pod never ready")

        with pytest.raises(TimeoutError):
            svc.resume_sandbox("abc12345")

        spans = {span.name: span for span in exporter.get_finished_spans()}
        resume = spans["sandbox.resume"]
        assert resume.attributes["litterbox.sandbox.id"] == "abc12345"
        assert resume.attributes["error.type"] == "TimeoutError"
        assert resume.status.status_code is StatusCode.ERROR
    finally:
        patch.stopall()
        provider.shutdown()


def test_create_and_proxy_metrics_are_recorded() -> None:
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    meter = provider.get_meter("test")
    try:
        with patch(
            "orchestrator.services.metrics.otel_metrics.get_meter",
            return_value=meter,
        ):
            reset_otel_instruments()
            sandbox_metrics.record_create(
                template_id="ubuntu", duration=1.25, success=True, source="direct"
            )
            sandbox_metrics.record_proxy(
                method="POST",
                envd_path="process.Process/Start",
                duration=0.5,
                status_code=200,
            )
            sandbox_metrics.record_proxy(
                method="POST",
                envd_path="process.Process/Start",
                duration=0.2,
                error="ConnectError",
            )

        data = reader.get_metrics_data()
        metrics = {
            metric.name: metric
            for resource in data.resource_metrics
            for scope in resource.scope_metrics
            for metric in scope.metrics
        }

        create_duration = metrics["litterbox.sandbox.create.duration"]
        point = create_duration.data.data_points[0]
        assert point.sum == 1.25
        assert dict(point.attributes)["litterbox.outcome"] == "success"

        create_attempts = metrics["litterbox.sandbox.create.attempts"]
        assert create_attempts.data.data_points[0].value == 1

        proxy_requests = metrics["litterbox.envd.proxy.requests"]
        assert sum(point.value for point in proxy_requests.data.data_points) == 2

        proxy_errors = metrics["litterbox.envd.proxy.errors"]
        error_points = [
            point
            for point in proxy_errors.data.data_points
            if dict(point.attributes)["error.type"] == "ConnectError"
        ]
        assert len(error_points) == 1
        assert error_points[0].value == 1
    finally:
        reset_otel_instruments()
        provider.shutdown()
