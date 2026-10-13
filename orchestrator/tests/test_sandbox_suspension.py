from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

import orchestrator.main as main_module
from orchestrator.config import Settings
from orchestrator.domain.models import SandboxStatus
from orchestrator.infra.kubernetes import KubernetesGateway, SandboxNotRunningError
from orchestrator.infra.ttl_queue import TTLEntry
from orchestrator.services.sandboxes import SandboxService
from orchestrator.utils import utcnow


class RecordingTTLQueue:
    def __init__(self) -> None:
        self.scheduled: list[tuple[TTLEntry, object]] = []
        self.unscheduled: list[TTLEntry] = []

    def schedule(self, entry: TTLEntry, expires_at) -> None:
        self.scheduled.append((entry, expires_at))

    def unschedule(self, entry: TTLEntry) -> None:
        self.unscheduled.append(entry)


class RecordingGateway:
    namespace = "default"

    def __init__(self, *, replicas: int = 1, annotations: dict[str, str] | None = None) -> None:
        self.deployment = SimpleNamespace(
            metadata=SimpleNamespace(
                name="sbx-suspended",
                annotations=dict(annotations or {}),
                labels={},
            ),
            spec=SimpleNamespace(replicas=replicas),
        )
        self.scale_calls: list[tuple[str, int]] = []
        self.patch_calls: list[tuple[str, dict]] = []
        self.ready_selectors: list[str] = []
        self.deleted_claims: list[str] = []
        self.deleted_deployments: list[str] = []

    def read_deployment(self, sandbox_id: str):
        assert sandbox_id == self.deployment.metadata.name
        return self.deployment

    def list_deployments(self, _label_selector: str):
        return [self.deployment]

    def scale_deployment(self, sandbox_id: str, replicas: int) -> None:
        assert sandbox_id == self.deployment.metadata.name
        self.scale_calls.append((sandbox_id, replicas))
        self.deployment.spec.replicas = replicas

    def patch_deployment(self, sandbox_id: str, body: dict) -> None:
        assert sandbox_id == self.deployment.metadata.name
        self.patch_calls.append((sandbox_id, body))
        metadata = body.get("metadata", {})
        if "annotations" in metadata:
            annotations = self.deployment.metadata.annotations
            for key, value in metadata["annotations"].items():
                if value is None:
                    annotations.pop(key, None)
                else:
                    annotations[key] = value

    def wait_for_pod_ready(self, label_selector: str):
        self.ready_selectors.append(label_selector)
        return SimpleNamespace(metadata=SimpleNamespace(name="pod-sbx-suspended"))

    def delete_persistent_volume_claim(self, name: str) -> None:
        self.deleted_claims.append(name)

    def delete_deployment(self, name: str, grace_period_seconds: int = 0) -> None:
        self.deleted_deployments.append(name)

    def list_services(self, _label_selector: str):
        return []


def build_service(
    *,
    replicas: int = 1,
    annotations: dict[str, str] | None = None,
) -> tuple[SandboxService, RecordingGateway, RecordingTTLQueue]:
    gateway = RecordingGateway(replicas=replicas, annotations=annotations)
    ttl_queue = RecordingTTLQueue()
    service = object.__new__(SandboxService)
    service.gateway = gateway
    service.ttl_queue = ttl_queue
    service.settings = Settings()
    service.expose_service = None
    service.get_sandbox = lambda sandbox_id: SimpleNamespace(
        id=sandbox_id,
        status=SandboxStatus.STOPPED if gateway.deployment.spec.replicas == 0 else SandboxStatus.RUNNING,
    )
    return service, gateway, ttl_queue


def test_suspend_scales_to_zero_without_deleting_workspace_pvc() -> None:
    service, gateway, _ = build_service()

    sandbox = service.suspend_sandbox("sbx-suspended")

    assert sandbox.status == SandboxStatus.STOPPED
    assert gateway.scale_calls == [("sbx-suspended", 0)]
    assert gateway.deleted_claims == []


def test_suspend_is_idempotent_when_deployment_is_already_stopped() -> None:
    service, gateway, _ = build_service(replicas=0)

    sandbox = service.suspend_sandbox("sbx-suspended")

    assert sandbox.status == SandboxStatus.STOPPED
    assert gateway.scale_calls == []


def test_resume_scales_to_one_and_waits_for_running_pod() -> None:
    service, gateway, _ = build_service(replicas=0)

    sandbox = service.resume_sandbox("sbx-suspended")

    assert sandbox.status == SandboxStatus.RUNNING
    assert gateway.scale_calls == [("sbx-suspended", 1)]
    assert gateway.ready_selectors == ["app=sbx-suspended,component=sandbox"]


def test_resume_is_idempotent_when_deployment_is_already_running() -> None:
    service, gateway, _ = build_service()

    service.resume_sandbox("sbx-suspended")

    assert gateway.scale_calls == []
    assert gateway.ready_selectors == []


def test_ttl_expiry_suspends_and_clears_active_schedule() -> None:
    annotations = {
        "litterbox.io/ttl-seconds": "60",
        "litterbox.io/expires-at": (utcnow() - timedelta(seconds=1)).isoformat(),
        "litterbox.io/ttl-token": "ttl-expired",
        "litterbox.io/last-ttl-renewal": utcnow().isoformat(),
    }
    service, gateway, ttl_queue = build_service(annotations=annotations)

    assert service.delete_if_ttl_due("sbx-suspended", "ttl-expired") is True

    assert gateway.scale_calls == [("sbx-suspended", 0)]
    assert gateway.deleted_claims == []
    assert gateway.deleted_deployments == []
    assert ttl_queue.unscheduled == [TTLEntry(sandbox_id="sbx-suspended", ttl_token="ttl-expired")]
    assert "litterbox.io/expires-at" not in gateway.deployment.metadata.annotations
    assert "litterbox.io/ttl-token" not in gateway.deployment.metadata.annotations
    assert "litterbox.io/last-ttl-renewal" not in gateway.deployment.metadata.annotations
    assert "litterbox.io/ttl-suspended-at" in gateway.deployment.metadata.annotations
    assert gateway.deployment.metadata.annotations["litterbox.io/ttl-seconds"] == "60"


def test_cleanup_expired_suspends_without_deleting_workspace_pvc() -> None:
    annotations = {
        "litterbox.io/ttl-seconds": "60",
        "litterbox.io/expires-at": (utcnow() - timedelta(seconds=1)).isoformat(),
        "litterbox.io/ttl-token": "ttl-expired",
    }
    service, gateway, _ = build_service(annotations=annotations)

    assert service.cleanup_expired() == 1

    assert gateway.scale_calls == [("sbx-suspended", 0)]
    assert gateway.deleted_claims == []
    assert gateway.deleted_deployments == []


def test_resume_rearms_ttl_suspended_sandbox() -> None:
    annotations = {
        "litterbox.io/ttl-seconds": "60",
        "litterbox.io/ttl-suspended-at": utcnow().isoformat(),
    }
    service, gateway, ttl_queue = build_service(replicas=0, annotations=annotations)

    service.resume_sandbox("sbx-suspended")

    current_annotations = gateway.deployment.metadata.annotations
    assert current_annotations["litterbox.io/ttl-seconds"] == "60"
    assert "litterbox.io/expires-at" in current_annotations
    assert current_annotations["litterbox.io/ttl-token"].startswith("ttl-")
    assert "litterbox.io/ttl-suspended-at" not in current_annotations
    assert ttl_queue.scheduled[0][0].sandbox_id == "sbx-suspended"


def test_unlock_explicitly_removes_lock_annotations() -> None:
    annotations = {
        "litterbox.io/resume-locked": "true",
        "litterbox.io/resume-locked-at": utcnow().isoformat(),
        "litterbox.io/ttl-seconds": "60",
    }
    service, gateway, _ = build_service(annotations=annotations)

    service.unlock_sandbox("sbx-suspended")

    current_annotations = gateway.deployment.metadata.annotations
    assert "litterbox.io/resume-locked" not in current_annotations
    assert "litterbox.io/resume-locked-at" not in current_annotations
    patch_annotations = gateway.patch_calls[-1][1]["metadata"]["annotations"]
    assert patch_annotations["litterbox.io/resume-locked"] is None
    assert patch_annotations["litterbox.io/resume-locked-at"] is None


def test_delete_removes_workspace_pvc_after_deployment() -> None:
    service, gateway, _ = build_service()
    service._unschedule_current_ttl = lambda _sandbox_id: None
    service.template_service = SimpleNamespace(get_template=lambda _template_id: None)
    service.webhook_dispatcher = SimpleNamespace(dispatch=lambda **_kwargs: None)

    service.delete_sandbox("sbx-suspended")

    assert gateway.deleted_deployments == ["sbx-suspended"]
    assert gateway.deleted_claims == ["workspace-sbx-suspended"]


def test_gateway_raises_typed_error_when_sandbox_has_no_running_pod() -> None:
    gateway = object.__new__(KubernetesGateway)
    gateway.list_pods = lambda _selector: []

    with pytest.raises(SandboxNotRunningError, match="sbx-stopped"):
        gateway.get_first_running_pod("sbx-stopped")


def test_removed_workspace_endpoints_return_not_found(monkeypatch) -> None:
    container = SimpleNamespace(settings=Settings())
    monkeypatch.setattr(main_module, "build_container", lambda: container)

    with TestClient(main_module.app) as client:
        responses = [
            client.post("/api/v1/sandboxes/sbx-stopped/exec", json={"command": ["pwd"]}),
            client.get("/api/v1/sandboxes/sbx-stopped/files", params={"path": "/workspace"}),
            client.put(
                "/api/v1/sandboxes/sbx-stopped/files",
                params={"path": "/workspace/file.txt"},
                content=b"workspace",
            ),
            client.delete(
                "/api/v1/sandboxes/sbx-stopped/files",
                params={"path": "/workspace/file.txt"},
            ),
        ]

    assert [response.status_code for response in responses] == [404, 404, 404, 404]


class LifecycleRouteService:
    def __init__(self) -> None:
        self.suspended: list[str] = []
        self.resumed: list[str] = []

    def suspend_sandbox(self, sandbox_id: str):
        self.suspended.append(sandbox_id)
        return {"id": sandbox_id, "status": SandboxStatus.STOPPED}

    def resume_sandbox(self, sandbox_id: str):
        self.resumed.append(sandbox_id)
        return {"id": sandbox_id, "status": SandboxStatus.RUNNING}


def test_lifecycle_routes_delegate_to_sandbox_service(monkeypatch) -> None:
    sandbox_service = LifecycleRouteService()
    container = SimpleNamespace(settings=Settings(), sandbox_service=sandbox_service)
    monkeypatch.setattr(main_module, "build_container", lambda: container)

    with TestClient(main_module.app) as client:
        suspend = client.post("/api/v1/sandboxes/sbx-suspended/suspend")
        resume = client.post("/api/v1/sandboxes/sbx-suspended/resume")

    assert suspend.status_code == 200
    assert resume.status_code == 200
    assert sandbox_service.suspended == ["sbx-suspended"]
    assert sandbox_service.resumed == ["sbx-suspended"]
