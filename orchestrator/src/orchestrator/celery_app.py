from __future__ import annotations

from celery import Celery
from celery.signals import worker_process_init, worker_process_shutdown

from orchestrator.config import get_settings
from orchestrator.telemetry import configure_telemetry, shutdown_telemetry
from orchestrator.worker_profiles import queue_for_worker

settings = get_settings()

celery_app = Celery(
    "orchestrator",
    broker=settings.celery.broker_url,
    backend=settings.celery.result_backend,
    include=["orchestrator.tasks"],
)

webhook_queue = queue_for_worker("webhook")

celery_app.conf.update(
    task_default_queue="default",
    task_routes={
        "orchestrator.tasks.deliver_webhook_event": {"queue": webhook_queue},
    },
    timezone="UTC",
    enable_utc=True,
)


@worker_process_init.connect
def _init_worker_telemetry(**_kwargs) -> None:
    # Runs after Celery forks each prefork child; configuring the SDK in the
    # parent would leave exporter threads in the wrong process.
    configure_telemetry("worker")


@worker_process_shutdown.connect
def _shutdown_worker_telemetry(**_kwargs) -> None:
    shutdown_telemetry()
