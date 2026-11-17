from __future__ import annotations

import time

from orchestrator.domain.models import (
    AllocateSandboxRequest,
    CreatePoolRequest,
    Pool,
    PoolListResponse,
    PoolState,
    PoolStatus,
    SandboxResponse,
    UpdatePoolRequest,
)
from orchestrator.infra.sandbox_pool_crd import SandboxPoolRepository
from orchestrator.services.sandboxes import SandboxService
from orchestrator.services.templates import TemplateService
from orchestrator.utils import utcnow


class PoolService:
    def __init__(
        self,
        repository: SandboxPoolRepository,
        sandbox_service: SandboxService,
        template_service: TemplateService,
    ) -> None:
        self.repository = repository
        self.sandbox_service = sandbox_service
        self.template_service = template_service

    def _pool_ttl_seconds(self, template_id: str) -> int:
        template = self.sandbox_service.get_template(template_id)
        if template.ttl_seconds is None:
            return self.sandbox_service.settings.ttl.default_ttl_seconds
        return template.ttl_seconds

    # ---- CRUD ----

    def create_pool(self, template_id: str, req: CreatePoolRequest) -> PoolStatus:
        template = self.template_service.get_template(template_id)
        if self.repository.get(template_id) is not None:
            raise ValueError(f"pool already exists for template {template_id}")
        self.sandbox_service.ensure_template(template)
        now = utcnow()
        target_ready = req.target_ready or req.min_ready
        pool = Pool(
            template_id=template_id,
            enabled=target_ready > 0,
            min_ready=req.min_ready,
            target_ready=target_ready,
            max_creating=req.max_creating,
            sandbox_template={},
            created_at=now,
            updated_at=now,
        )
        self.repository.save(pool)
        return self.get_pool_status(template_id)

    def get_pool_status(self, template_id: str) -> PoolStatus:
        pool = self.repository.get(template_id)
        if pool is None:
            raise ValueError(f"pool not found for template {template_id}")
        counts = self.repository.get_status(template_id)
        return PoolStatus(
            template_id=pool.template_id,
            enabled=pool.enabled,
            min_ready=pool.min_ready,
            target_ready=pool.target_ready,
            max_creating=pool.max_creating,
            ready=int(counts.get("ready", 0)),
            creating=int(counts.get("creating", 0)),
            allocated=int(counts.get("allocated", 0)),
            failed=int(counts.get("failed", 0)),
            terminating=int(counts.get("terminating", 0)),
        )

    def update_pool(self, template_id: str, req: UpdatePoolRequest) -> PoolStatus:
        pool = self.repository.get(template_id)
        if pool is None:
            raise ValueError(f"pool not found for template {template_id}")
        updates = req.model_dump(exclude_none=True)
        if "min_ready" in updates:
            updates["enabled"] = updates["min_ready"] > 0
            if updates["min_ready"] == 0:
                updates["target_ready"] = 0
            elif "target_ready" not in updates and pool.target_ready == 0:
                updates["target_ready"] = updates["min_ready"]
        updated = pool.model_copy(update={**updates, "updated_at": utcnow()})
        self.repository.save(updated)
        return self.get_pool_status(template_id)

    def delete_pool(self, template_id: str) -> None:
        if self.repository.get(template_id) is None:
            return
        self.repository.delete(template_id)

    def list_pools(self) -> PoolListResponse:
        pools = [self.get_pool_status(pool.template_id) for pool in self.repository.list()]
        return PoolListResponse(pools=pools, total=len(pools))

    # ---- Allocate / Release ----

    def allocate_sandbox(self, req: AllocateSandboxRequest) -> SandboxResponse:
        from orchestrator.services.metrics import sandbox_metrics  # 延迟导入，避免循环

        pool = self.repository.get(req.template_id)
        pool_state = PoolState.ALLOCATED if pool and pool.enabled else PoolState.NONE
        ttl_seconds = self._pool_ttl_seconds(req.template_id)
        _t0 = time.perf_counter()
        sandbox = self.sandbox_service.create_sandbox(
            template_id=req.template_id,
            name=req.name,
            metadata=req.metadata,
            env=req.env,
            pool_state=pool_state,
            wait_ready=True,
            dispatch_events=True,
            ttl_seconds=ttl_seconds,
            workspace=req.workspace,
        )
        sandbox_metrics.record_create(
            template_id=req.template_id,
            duration=time.perf_counter() - _t0,
            success=True,
            source="pool" if pool_state != PoolState.NONE else "direct",
        )
        return sandbox

    def release_sandbox(self, sandbox_id: str) -> None:
        self.sandbox_service.delete_sandbox(sandbox_id)

    def renew_sandbox_ttl(self, sandbox_id: str, ttl: int) -> None:
        self.sandbox_service.renew_ttl(sandbox_id, ttl)

    def update_sandbox_ttl(self, sandbox_id: str, ttl_seconds: int) -> None:
        self.sandbox_service.update_ttl(sandbox_id, ttl_seconds)
