from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import orchestrator.main as main_module
from orchestrator.config import AuthConfig, Settings


class DummyTemplateService:
    def list_templates(self, _params):
        return {"templates": [], "total": 0}


class DummySession:
    def is_open(self) -> bool:
        return False

    def update(self, _timeout: int) -> None:
        return None

    def peek_stdout(self) -> bool:
        return False

    def peek_stderr(self) -> bool:
        return False

    def read_stdout(self) -> str:
        return ""

    def read_stderr(self) -> str:
        return ""

    def write_stdin(self, _data: str) -> None:
        return None

    def write_channel(self, _channel: int, _data: str) -> None:
        return None

    def close(self) -> None:
        return None


class DummyGateway:
    def __init__(self) -> None:
        self.open_shell_calls = 0

    def open_shell(self, _sandbox_id: str) -> DummySession:
        self.open_shell_calls += 1
        return DummySession()


def build_test_client(monkeypatch, bearer_token: str):
    gateway = DummyGateway()
    container = SimpleNamespace(
        settings=Settings(auth=AuthConfig(bearer_token=bearer_token)),
        template_service=DummyTemplateService(),
        gateway=gateway,
    )
    monkeypatch.setattr(main_module, "build_container", lambda: container)
    return TestClient(main_module.app), gateway


def test_http_api_open_when_bearer_token_not_configured(monkeypatch) -> None:
    client, _ = build_test_client(monkeypatch, "")
    with client:
        response = client.get("/api/v1/templates")
    assert response.status_code == 200


def test_http_api_requires_authorization_when_token_configured(monkeypatch) -> None:
    client, _ = build_test_client(monkeypatch, "test-secret")
    with client:
        response = client.get("/api/v1/templates")
    assert response.status_code == 401
    assert response.json()["error"] == "Unauthorized"


def test_http_api_accepts_valid_bearer_token(monkeypatch) -> None:
    client, _ = build_test_client(monkeypatch, "test-secret")
    with client:
        response = client.get("/api/v1/templates", headers={"Authorization": "Bearer test-secret"})
    assert response.status_code == 200


def test_http_api_rejects_invalid_bearer_token(monkeypatch) -> None:
    client, _ = build_test_client(monkeypatch, "test-secret")
    with client:
        response = client.get("/api/v1/templates", headers={"Authorization": "Bearer wrong-token"})
    assert response.status_code == 401


def test_terminal_websocket_rejects_missing_token(monkeypatch) -> None:
    client, gateway = build_test_client(monkeypatch, "test-secret")
    with client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/api/v1/sandboxes/sbx-1/terminal"):
                pass
    assert gateway.open_shell_calls == 0


def test_terminal_websocket_accepts_query_token(monkeypatch) -> None:
    client, gateway = build_test_client(monkeypatch, "test-secret")
    with client:
        with client.websocket_connect("/api/v1/sandboxes/sbx-1/terminal?token=test-secret"):
            pass
    assert gateway.open_shell_calls == 1
