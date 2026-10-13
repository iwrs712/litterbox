from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from orchestrator.auth import is_e2b_authorized
import orchestrator.main as main_module
from orchestrator.config import AuthConfig, Settings


class DummyTemplateService:
    def list_templates(self, _params):
        return {"templates": [], "total": 0}


def build_test_client(monkeypatch, bearer_token: str):
    container = SimpleNamespace(
        settings=Settings(auth=AuthConfig(bearer_token=bearer_token)),
        template_service=DummyTemplateService(),
    )
    monkeypatch.setattr(main_module, "build_container", lambda: container)
    return TestClient(main_module.app)


def test_http_api_open_when_bearer_token_not_configured(monkeypatch) -> None:
    client = build_test_client(monkeypatch, "")
    with client:
        response = client.get("/api/v1/templates")
    assert response.status_code == 200


def test_http_api_requires_authorization_when_token_configured(monkeypatch) -> None:
    client = build_test_client(monkeypatch, "test-secret")
    with client:
        response = client.get("/api/v1/templates")
    assert response.status_code == 401
    assert response.json()["error"] == "Unauthorized"


def test_http_api_accepts_valid_bearer_token(monkeypatch) -> None:
    client = build_test_client(monkeypatch, "test-secret")
    with client:
        response = client.get("/api/v1/templates", headers={"Authorization": "Bearer test-secret"})
    assert response.status_code == 200


def test_http_api_rejects_invalid_bearer_token(monkeypatch) -> None:
    client = build_test_client(monkeypatch, "test-secret")
    with client:
        response = client.get("/api/v1/templates", headers={"Authorization": "Bearer wrong-token"})
    assert response.status_code == 401


def test_e2b_accepts_envd_access_token() -> None:
    assert is_e2b_authorized("test-secret", None, None, "test-secret") is True


def test_removed_rest_data_plane_routes_return_not_found(monkeypatch) -> None:
    client = build_test_client(monkeypatch, "test-secret")
    with client:
        headers = {"Authorization": "Bearer test-secret"}
        responses = [
            client.post("/api/v1/sandboxes/sbx-1/exec", json={"command": ["pwd"]}, headers=headers),
            client.get("/api/v1/sandboxes/sbx-1/files", headers=headers),
            client.put("/api/v1/sandboxes/sbx-1/files", content=b"data", headers=headers),
            client.delete("/api/v1/sandboxes/sbx-1/files", headers=headers),
        ]

    assert [response.status_code for response in responses] == [404, 404, 404, 404]


def test_removed_websocket_data_plane_routes_do_not_upgrade(monkeypatch) -> None:
    client = build_test_client(monkeypatch, "test-secret")
    with client:
        for path in (
            "/api/v1/sandboxes/sbx-1/terminal?token=test-secret",
            "/api/v1/sandboxes/sbx-1/acp?token=test-secret",
        ):
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect(path):
                    pass
