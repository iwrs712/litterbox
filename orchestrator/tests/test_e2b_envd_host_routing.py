from __future__ import annotations

from types import SimpleNamespace

from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import orchestrator.main as main_module
from orchestrator.config import E2BConfig, EnvdConfig, Settings
from orchestrator.domain.models import SandboxStatus
from orchestrator.routes.envd import parse_sandbox_envd_host


def test_parse_sandbox_envd_host_accepts_configured_port_and_domain() -> None:
    assert parse_sandbox_envd_host("49983-sbx-123.example.com", "example.com", 49983) == "sbx-123"
    assert parse_sandbox_envd_host("49983-sbx-123.example.com:443", "example.com", 49983) == "sbx-123"


def test_parse_sandbox_envd_host_rejects_other_ports_or_domains() -> None:
    assert parse_sandbox_envd_host("50000-sbx-123.example.com", "example.com", 49983) is None
    assert parse_sandbox_envd_host("49983-sbx-123.other.cn", "example.com", 49983) is None


def test_e2b_sandbox_host_is_rewritten_to_existing_envd_proxy(monkeypatch) -> None:
    calls = []

    async def proxy(sandbox_id, envd_path, request):
        calls.append((sandbox_id, envd_path, request.url.path))
        return JSONResponse({"ok": True})

    container = SimpleNamespace(
        settings=Settings(
            auth={"bearer_token": ""},
            e2b=E2BConfig(enabled=True, domain="example.com"),
            envd=EnvdConfig(port=49983),
        ),
        sandbox_service=SimpleNamespace(
            get_sandbox=lambda _sandbox_id: SimpleNamespace(status=SandboxStatus.RUNNING),
        ),
        envd_proxy_service=SimpleNamespace(proxy=proxy),
    )
    monkeypatch.setattr(main_module, "build_container", lambda: container)

    with TestClient(main_module.app) as client:
        response = client.post(
            "/process.Process/Start",
            headers={"Host": "49983-sbx-123.example.com"},
            json={"command": "echo hi"},
        )

    assert response.status_code == 200
    assert calls == [("sbx-123", "process.Process/Start", "/api/v1/sandboxes/sbx-123/envd/process.Process/Start")]


def test_e2b_sandbox_host_is_not_rewritten_when_e2b_is_disabled(monkeypatch) -> None:
    container = SimpleNamespace(
        settings=Settings(
            auth={"bearer_token": ""},
            e2b=E2BConfig(enabled=False, domain="example.com"),
            envd=EnvdConfig(port=49983),
        ),
    )
    monkeypatch.setattr(main_module, "build_container", lambda: container)

    with TestClient(main_module.app) as client:
        response = client.get("/health", headers={"Host": "49983-sbx-123.example.com"})

    assert response.status_code == 200
