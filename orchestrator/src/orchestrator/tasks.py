from __future__ import annotations

from functools import lru_cache
import logging

from orchestrator.celery_app import celery_app
from orchestrator.container import Container, build_container

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_worker_container() -> Container:
    return build_container()


@celery_app.task(
    name="orchestrator.tasks.deliver_webhook_event",
    bind=True,
)
def deliver_webhook_event(self, webhook_id: str, payload_data: dict) -> None:
    """Deliver a single webhook attempt.

    Retry scheduling is handled here (via Celery ``self.retry``) rather than
    with a blocking ``time.sleep`` loop inside WebhookService, so worker
    threads are freed between attempts.

    Retry budget is read from the webhook's own ``retry`` config:
      - ``max_attempts`` — total attempts including the first one
      - ``interval_ms``  — fixed delay between attempts (countdown)
    """
    container = get_worker_container()
    try:
        container.webhook_service.deliver(webhook_id, payload_data)
    except Exception as exc:  # noqa: BLE001
        # Fetch the webhook config to honour per-webhook retry settings.
        # If the webhook no longer exists, just log and stop.
        try:
            webhook = container.webhook_service.get_webhook(webhook_id)
        except Exception:
            logger.exception(
                "webhook not found, aborting delivery webhook_id=%s event_type=%s",
                webhook_id,
                payload_data.get("event_type", ""),
            )
            return

        max_attempts = max(webhook.retry.max_attempts, 1)
        countdown_s = webhook.retry.interval_ms / 1000

        if self.request.retries < max_attempts - 1:
            logger.warning(
                "webhook delivery failed, will retry in %.1fs "
                "webhook_id=%s attempt=%s/%s event_type=%s error=%s",
                countdown_s,
                webhook_id,
                self.request.retries + 1,
                max_attempts,
                payload_data.get("event_type", ""),
                exc,
            )
            raise self.retry(exc=exc, countdown=countdown_s, max_retries=max_attempts - 1)

        logger.error(
            "webhook delivery exhausted all %s attempts "
            "webhook_id=%s event_type=%s last_error=%s",
            max_attempts,
            webhook_id,
            payload_data.get("event_type", ""),
            exc,
            exc_info=True,
        )


@celery_app.task(name="orchestrator.tasks.reconcile_pool", bind=True, max_retries=2, default_retry_delay=5)
def reconcile_pool(self, template_id: str) -> None:
    container = get_worker_container()
    try:
        container.pool_service.reconcile_pool(template_id)
    except Exception as exc:
        self.retry(exc=exc)

