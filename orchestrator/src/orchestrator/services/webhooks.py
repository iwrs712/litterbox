from __future__ import annotations

import logging

import httpx

from orchestrator.celery_app import celery_app
from orchestrator.config import Settings
from orchestrator.domain.models import (
    CreateWebhookRequest,
    SandboxResponse,
    Template,
    UpdateWebhookRequest,
    Webhook,
    WebhookEvent,
    WebhookK8sInfo,
    WebhookListParams,
    WebhookPayload,
)
from orchestrator.infra.repositories import WebhookRepository
from orchestrator.worker_profiles import queue_for_worker
from orchestrator.utils import short_id, utcnow

logger = logging.getLogger(__name__)
_MAX_LOG_BODY_CHARS = 4000


class WebhookService:
    def __init__(self, repository: WebhookRepository, settings: Settings) -> None:
        self.repository = repository
        self.settings = settings
        # Shared client for connection reuse across deliveries.
        self._http = httpx.Client(
            timeout=settings.webhook.timeout_ms / 1000,
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
        )

    def create_webhook(self, req: CreateWebhookRequest) -> Webhook:
        now = utcnow()
        webhook = Webhook(
            id=req.id or short_id(),
            name=req.name,
            user_id=req.user_id,
            url=req.url,
            token=req.token,
            template_ids=req.template_ids,
            events=req.events,
            retry=req.retry,
            enabled=req.enabled if req.enabled is not None else True,
            created_at=now,
            updated_at=now,
        )
        self._validate_events(webhook.events)
        return self.repository.save(webhook)

    def get_webhook(self, webhook_id: str) -> Webhook:
        return self.repository.get(webhook_id)

    def list_webhooks(self, params: WebhookListParams) -> list[Webhook]:
        return self.repository.list(params.user_id)

    def update_webhook(self, webhook_id: str, req: UpdateWebhookRequest) -> Webhook:
        webhook = self.repository.get(webhook_id)
        updates = req.model_dump(exclude_none=True)
        candidate = webhook.model_copy(update={**updates, "updated_at": utcnow()})
        self._validate_events(candidate.events)
        return self.repository.save(candidate)

    def delete_webhook(self, webhook_id: str) -> None:
        self.repository.delete(webhook_id)

    def deliver(self, webhook_id: str, payload_data: dict) -> None:
        webhook = self.repository.get(webhook_id)
        if not webhook.enabled:
            return
        self._send_once(webhook, WebhookPayload.model_validate(payload_data))

    @staticmethod
    def _validate_events(events: list[WebhookEvent]) -> None:
        allowed = {
            WebhookEvent.SANDBOX_STARTED,
            WebhookEvent.SANDBOX_READY,
            WebhookEvent.SANDBOX_DELETED,
        }
        for event in events:
            if event not in allowed:
                raise ValueError(f"unsupported webhook event: {event}")

    @staticmethod
    def _safe_headers(headers: dict[str, str]) -> dict[str, str]:
        safe = dict(headers)
        if "Authorization" in safe:
            safe["Authorization"] = "***"
        return safe

    @staticmethod
    def _truncate_body(body: str, limit: int = _MAX_LOG_BODY_CHARS) -> str:
        if len(body) <= limit:
            return body
        return f"{body[:limit]}...(truncated {len(body) - limit} chars)"

    def _send_once(self, webhook: Webhook, payload: WebhookPayload) -> None:
        """Perform a single HTTP delivery attempt.  Raises on any failure so
        the Celery task can schedule a retry via ``self.retry(countdown=...)``.
        """
        payload_data = payload.model_dump(mode="json")
        headers = {"Content-Type": "application/json"}
        if webhook.token:
            headers["Authorization"] = f"Bearer {webhook.token}"
        safe_headers = self._safe_headers(headers)
        timeout = webhook.retry.timeout_ms / 1000
        logger.info(
            "sending webhook request webhook_id=%s url=%s headers=%s payload=%s",
            webhook.id,
            webhook.url,
            safe_headers,
            payload_data,
        )
        response = self._http.post(webhook.url, headers=headers, json=payload_data, timeout=timeout)
        logger.info(
            "received webhook response webhook_id=%s url=%s status_code=%s headers=%s body=%s",
            webhook.id,
            webhook.url,
            response.status_code,
            dict(response.headers),
            self._truncate_body(response.text),
        )
        response.raise_for_status()


class WebhookDispatcher:
    def __init__(self, repository: WebhookRepository, settings: Settings) -> None:
        self.repository = repository
        self.settings = settings

    def dispatch(
        self,
        *,
        event: WebhookEvent,
        sandbox: SandboxResponse,
        template: Template | None,
        namespace: str,
        pod_name: str = "",
        pod_ip: str = "",
        node_name: str = "",
        deletion_reason: str = "",
    ) -> None:
        user_id = sandbox.metadata.get("user_id", "")
        hooks = self.repository.list(user_id)
        payload = WebhookPayload(
            event_id=short_id(),
            event_type=event,
            occurred_at=utcnow(),
            deletion_reason=deletion_reason,
            sandbox=sandbox,
            template=template,
            kubernetes=WebhookK8sInfo(
                namespace=namespace,
                pod_name=pod_name,
                pod_ip=pod_ip,
                node_name=node_name,
                container_name="main" if pod_name else "",
            ),
        )
        for hook in hooks:
            if not hook.enabled:
                continue
            if hook.events and event not in hook.events:
                continue
            if hook.template_ids and template and template.id not in hook.template_ids:
                continue
            celery_app.send_task(
                "orchestrator.tasks.deliver_webhook_event",
                kwargs={
                    "webhook_id": hook.id,
                    "payload_data": payload.model_dump(mode="json"),
                },
                queue=queue_for_worker("webhook"),
            )
