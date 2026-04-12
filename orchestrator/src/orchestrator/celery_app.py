from __future__ import annotations

from celery import Celery

from orchestrator.config import get_settings
from orchestrator.worker_profiles import queue_for_worker

settings = get_settings()

celery_app = Celery(
    "orchestrator",
    broker=settings.celery.broker_url,
    backend=settings.celery.result_backend,
    include=["orchestrator.tasks"],
)

webhook_queue = queue_for_worker("webhook")
pool_queue = queue_for_worker("pool")

celery_app.conf.update(
    task_default_queue="default",
    task_routes={
        "orchestrator.tasks.deliver_webhook_event": {"queue": webhook_queue},
        "orchestrator.tasks.reconcile_pool": {"queue": pool_queue},
    },
    timezone="UTC",
    enable_utc=True,
)
