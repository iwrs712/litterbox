from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient

import orchestrator.main as main_module
from orchestrator.config import E2BConfig, Settings
from orchestrator.domain.models import SandboxStatus, WorkspaceConfig
from orchestrator.services.e2b import E2BControlPlaneService


class RecordingSandboxService:
    def __init__(self) -> None:
        self.created = []
        self.suspended = []
        self.resumed = []
        self.updated_ttls = []
        self.deleted = []
        self.sandbox = SimpleNamespace(
            id="sbx-123",
            name="job-1",
            template_id="python-worker",
            image="python:3.12-slim",
            cpu_millicores=1000,
            memory_mb=1024,
            status=SandboxStatus.RUNNING,
            terminating=False,
            pool_state="none",
            metadata={"job_id": "1001"},
            allocated_at=None,
            created_at=datetime(2026, 8, 31, 10, 0, tzinfo=UTC),
            updated_at=datetime(2026, 8, 31, 10, 0, 5, tzinfo=UTC),
            ttl_seconds=300,
            expires_at=datetime(2026, 8, 31, 10, 5, tzinfo=UTC),
            time_remaining_seconds=295,
            locked=False,
            workspace=WorkspaceConfig(
                enabled=True,
                mount_path="/workspace",
                size="1Gi",
                storage_class="litterbox-workspace-lvm",
            ),
        )

    def suspend_sandbox(self, sandbox_id: str):
        self.suspended.append(sandbox_id)
        return self.sandbox

    def resume_sandbox(self, sandbox_id: str):
        self.resumed.append(sandbox_id)
        return self.sandbox

    def update_ttl(self, sandbox_id: str, ttl_seconds: int) -> None:
        self.updated_ttls.append((sandbox_id, ttl_seconds))

    def get_sandbox(self, sandbox_id: str):
        assert sandbox_id == self.sandbox.id
        return self.sandbox


class RecordingPoolService:
    def __init__(self, sandbox_service: RecordingSandboxService) -> None:
        self.sandbox_service = sandbox_service
        self.requests = []

    def allocate_sandbox(self, request):
        self.requests.append(request)
        return self.sandbox_service.sandbox

    def release_sandbox(self, sandbox_id: str) -> None:
        self.sandbox_service.deleted.append(sandbox_id)


def build_client(monkeypatch):
    sandbox_service = RecordingSandboxService()
    pool_service = RecordingPoolService(sandbox_service)
    container = SimpleNamespace(
        settings=Settings(e2b=E2BConfig(enabled=True, api_key="e2b-secret", domain="runlet.cn")),
        sandbox_service=sandbox_service,
        pool_service=pool_service,
    )
    container.e2b_service = E2BControlPlaneService(
        container.settings,
        sandbox_service,
        pool_service,
    )
    monkeypatch.setattr(main_module, "build_container", lambda: container)
    return TestClient(main_module.app), container


def test_e2b_create_uses_native_fields_and_returns_unwrapped_response(monkeypatch) -> None:
    client, container = build_client(monkeypatch)

    with client:
        response = client.post(
            "/e2b/sandboxes",
            headers={"X-API-Key": "e2b-secret"},
            json={
                "templateID": "python-worker",
                "timeout": 300,
                "metadata": {"job_id": "1001"},
                "envVars": {"JOB_ID": "1001"},
                "secure": False,
                "allow_internet_access": True,
            },
        )

    assert response.status_code == 201
    assert response.json()["sandboxID"] == "sbx-123"
    assert response.json()["templateID"] == "python-worker"
    assert response.json()["clientID"] == "litterbox"
    assert response.json()["envdAccessToken"] == "e2b-secret"
    assert response.json()["domain"] == "runlet.cn"
    assert "success" not in response.json()
    request = container.pool_service.requests[0]
    assert request.template_id == "python-worker"
    assert request.env == ["JOB_ID=1001"]
    assert request.metadata == {"job_id": "1001"}


def test_e2b_api_key_is_required(monkeypatch) -> None:
    client, _ = build_client(monkeypatch)

    with client:
        response = client.get("/e2b/sandboxes/sbx-123")

    assert response.status_code == 401


def test_e2b_pause_rejects_memory_snapshot_and_filesystem_pause_delegates(monkeypatch) -> None:
    client, container = build_client(monkeypatch)

    with client:
        memory_response = client.post(
            "/e2b/sandboxes/sbx-123/pause",
            headers={"X-API-Key": "e2b-secret"},
            json={"memory": True},
        )
        filesystem_response = client.post(
            "/e2b/sandboxes/sbx-123/pause",
            headers={"X-API-Key": "e2b-secret"},
            json={"memory": False},
        )

    assert memory_response.status_code == 409
    assert filesystem_response.status_code == 200
    assert container.sandbox_service.suspended == ["sbx-123"]


def test_e2b_connect_and_timeout_map_to_existing_lifecycle(monkeypatch) -> None:
    client, container = build_client(monkeypatch)

    with client:
        connect = client.post(
            "/e2b/sandboxes/sbx-123/connect",
            headers={"X-API-Key": "e2b-secret"},
            json={"timeout": 600},
        )
        timeout = client.post(
            "/e2b/sandboxes/sbx-123/timeout",
            headers={"X-API-Key": "e2b-secret"},
            json={"timeout": 900},
        )

    assert connect.status_code == 200
    assert connect.json()["sandboxID"] == "sbx-123"
    assert timeout.status_code == 204
    assert container.sandbox_service.resumed == ["sbx-123"]
    assert container.sandbox_service.updated_ttls == [("sbx-123", 600), ("sbx-123", 900)]


def test_e2b_delete_maps_to_permanent_release(monkeypatch) -> None:
    client, container = build_client(monkeypatch)

    with client:
        response = client.delete(
            "/e2b/sandboxes/sbx-123",
            headers={"X-API-Key": "e2b-secret"},
        )

    assert response.status_code == 204
    assert container.sandbox_service.deleted == ["sbx-123"]
