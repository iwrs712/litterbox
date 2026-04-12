from __future__ import annotations

import logging
import time

from orchestrator.infra.ttl_queue import TTLQueueRepository
from orchestrator.services.sandboxes import SandboxService
from orchestrator.utils import utcnow


logger = logging.getLogger(__name__)


class TTLWorker:
    def __init__(
        self,
        queue: TTLQueueRepository,
        sandbox_service: SandboxService,
        poll_interval_seconds: float,
    ) -> None:
        self.queue = queue
        self.sandbox_service = sandbox_service
        self.poll_interval_seconds = poll_interval_seconds

    def run_forever(self) -> None:
        logger.info("ttl worker ready")
        while True:
            entry = self.queue.pop_due(utcnow())
            if entry is None:
                time.sleep(self.poll_interval_seconds)
                continue
            self.sandbox_service.delete_if_ttl_due(entry.sandbox_id, entry.ttl_token)
