from __future__ import annotations

from datetime import UTC, datetime

import httpx

from orchestrator.config import Settings
from orchestrator.domain.models import Webhook
from orchestrator.services.webhooks import WebhookService


class FakePayload:
    def model_dump(self, mode: str = "json") -> dict:
        return {
            "event_type": "sandbox_ready",
            "sandbox": {"id": "sbx-1"},
        }


class FakeClient:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def __enter__(self) -> "FakeClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def post(self, url: str, headers: dict[str, str], json: dict) -> httpx.Response:
        request = httpx.Request("POST", url, headers=headers)
        return httpx.Response(200, request=request, json={"ok": True})


def test_webhook_send_logs_request_and_response(monkeypatch, caplog) -> None:
    service = WebhookService(repository=None, settings=Settings())
    webhook = Webhook(
        id="wh-1",
        name="test",
        user_id="u-1",
        url="https://example.test/webhook",
        token="super-secret",
        created_at=datetime.now(tz=UTC),
        updated_at=datetime.now(tz=UTC),
    )

    monkeypatch.setattr(httpx, "Client", FakeClient)

    with caplog.at_level("INFO", logger="orchestrator.services.webhooks"):
        service._send(webhook, FakePayload())

    assert "sending webhook request webhook_id=wh-1" in caplog.text
    assert "received webhook response webhook_id=wh-1" in caplog.text
    assert "sandbox_ready" in caplog.text
    assert "status_code=200" in caplog.text
    assert "Authorization': '***'" in caplog.text
    assert "super-secret" not in caplog.text
