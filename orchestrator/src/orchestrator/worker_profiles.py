from __future__ import annotations

WORKER_QUEUES = {
    "webhook": "webhook_delivery",
    "pool": "pool_reconcile",
}


def queue_for_worker(worker_name: str) -> str:
    return WORKER_QUEUES.get(worker_name, worker_name)
