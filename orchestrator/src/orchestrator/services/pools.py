from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from redis import Redis

from orchestrator.domain.models import (
    AllocateSandboxRequest,
    CreatePoolRequest,
    Pool,
    PoolListResponse,
    PoolState,
    PoolStatus,
    QueryOptions,
    SandboxResponse,
    UpdatePoolRequest,
)
from orchestrator.infra.repositories import PoolRepository
from orchestrator.services.sandboxes import SandboxService
from orchestrator.services.templates import TemplateService
from orchestrator.utils import short_id, utcnow

logger = logging.getLogger(__name__)

_UNLOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
end
return 0
"""


class PoolService:
    def __init__(
        self,
        repository: PoolRepository,
        sandbox_service: SandboxService,
        template_service: TemplateService,
        redis_url: str,
    ) -> None:
        self.repository = repository
        self.sandbox_service = sandbox_service
        self.template_service = template_service
        self.redis = Redis.from_url(redis_url, decode_responses=True)
        self._unlock = self.redis.register_script(_UNLOCK_SCRIPT)

    @staticmethod
    def _lock_key(template_id: str) -> str:
        return f"pool:reconcile:{template_id}"

    @staticmethod
    def _claim_lock_key(template_id: str) -> str:
        return f"pool:claim:{template_id}"

    def _acquire_lock(self, template_id: str, ttl: int = 10) -> str | None:
        lock_value = short_id("lock-")
        if self.redis.set(self._lock_key(template_id), lock_value, nx=True, ex=ttl):
            return lock_value
        return None

    def _release_lock(self, template_id: str, lock_value: str) -> None:
        self._unlock(keys=[self._lock_key(template_id)], args=[lock_value])

    def _acquire_claim_lock(
        self,
        template_id: str,
        *,
        ttl: int = 10,
        wait_timeout: float = 5.0,
        retry_interval: float = 0.1,
    ) -> str | None:
        deadline = time.monotonic() + wait_timeout
        while time.monotonic() < deadline:
            lock_value = short_id("claim-")
            if self.redis.set(self._claim_lock_key(template_id), lock_value, nx=True, ex=ttl):
                return lock_value
            time.sleep(retry_interval)
        return None

    def _release_claim_lock(self, template_id: str, lock_value: str) -> None:
        self._unlock(keys=[self._claim_lock_key(template_id)], args=[lock_value])

    def _spawn_reconcile(self, template_id: str) -> None:
        from orchestrator.celery_app import celery_app
        celery_app.send_task("orchestrator.tasks.reconcile_pool", args=[template_id])

    def _pool_ttl_seconds(self, template_id: str) -> int:
        template = self.sandbox_service.get_template(template_id)
        return template.ttl_seconds or self.sandbox_service.settings.ttl.default_ttl_seconds

    def _deactivate_pool_sandboxes(self, template_id: str) -> None:
        sandboxes = self.sandbox_service.list_sandboxes(
            QueryOptions(template_id=template_id, page=1, page_size=1000)
        ).sandboxes
        for sandbox in sandboxes:
            if sandbox.pool_state == PoolState.NONE or sandbox.terminating:
                continue
            try:
                self.sandbox_service.update_pool_state(sandbox.id, PoolState.FAILED)
            except Exception:  # noqa: BLE001
                logger.exception("failed to deactivate pool sandbox %s", sandbox.id)

    # ---- CRUD ----

    def create_pool(self, template_id: str, req: CreatePoolRequest) -> PoolStatus:
        self.template_service.get_template(template_id)
        if self.repository.get(template_id) is not None:
            raise ValueError(f"pool already exists for template {template_id}")
        now = utcnow()
        pool = Pool(
            template_id=template_id,
            enabled=True,
            min_ready=req.min_ready,
            target_ready=req.target_ready or req.min_ready,
            max_creating=req.max_creating,
            created_at=now,
            updated_at=now,
        )
        self.repository.save(pool)
        self._spawn_reconcile(template_id)
        return self.get_pool_status(template_id)

    def get_pool(self, template_id: str) -> Pool | None:
        return self.repository.get(template_id)

    def get_pool_status(self, template_id: str) -> PoolStatus:
        pool = self.repository.get(template_id)
        if pool is None:
            raise ValueError(f"pool not found for template {template_id}")
        metrics = self._metrics(template_id)
        return PoolStatus(
            template_id=pool.template_id,
            enabled=pool.enabled,
            min_ready=pool.min_ready,
            target_ready=pool.target_ready,
            max_creating=pool.max_creating,
            ready=metrics["ready"],
            creating=metrics["creating"],
            allocated=metrics["allocated"],
            failed=metrics["failed"],
            terminating=metrics["terminating"],
        )

    def update_pool(self, template_id: str, req: UpdatePoolRequest) -> PoolStatus:
        pool = self.repository.get(template_id)
        if pool is None:
            raise ValueError(f"pool not found for template {template_id}")
        updates = req.model_dump(exclude_none=True)
        if "min_ready" in updates:
            updates["enabled"] = updates["min_ready"] > 0
        updated = pool.model_copy(update={**updates, "updated_at": utcnow()})
        self.repository.save(updated)
        self._spawn_reconcile(template_id)
        return self.get_pool_status(template_id)

    def delete_pool(self, template_id: str) -> None:
        pool = self.repository.get(template_id)
        if pool is not None and pool.enabled:
            self.repository.save(pool.model_copy(update={"enabled": False, "updated_at": utcnow()}))
        lock_value = self._acquire_claim_lock(template_id, ttl=60)
        if lock_value is None:
            raise RuntimeError(f"timed out acquiring pool claim lock for template {template_id}")
        try:
            self._deactivate_pool_sandboxes(template_id)
        finally:
            self._release_claim_lock(template_id, lock_value)
        sandboxes = self.sandbox_service.list_sandboxes(
            QueryOptions(template_id=template_id, page=1, page_size=1000)
        )
        for sandbox in sandboxes.sandboxes:
            # 只删除池管理的非活跃 sandbox（FAILED/CREATING/AVAILABLE）
            # ALLOCATED 状态表示 sandbox 正在被用户使用，不能强制删除
            if sandbox.pool_state in {PoolState.FAILED, PoolState.CREATING, PoolState.AVAILABLE}:
                try:
                    self.sandbox_service.delete_sandbox(sandbox.id)
                except Exception:  # noqa: BLE001
                    pass
        self.repository.delete(template_id)

    def list_pools(self) -> PoolListResponse:
        pools = [self.get_pool_status(pool.template_id) for pool in self.repository.list()]
        return PoolListResponse(pools=pools, total=len(pools))

    # ---- Allocate / Release ----

    def allocate_sandbox(self, req: AllocateSandboxRequest) -> SandboxResponse:
        from orchestrator.services.metrics import sandbox_metrics  # 延迟导入，避免循环

        pool = self.repository.get(req.template_id)
        if pool and pool.enabled:
            lock_value = self._acquire_claim_lock(req.template_id)
            if lock_value is None:
                raise RuntimeError(f"timed out acquiring pool claim lock for template {req.template_id}")
            allocated = None
            _t0 = time.perf_counter()
            try:
                available = self.sandbox_service.list_sandboxes(
                    QueryOptions(
                        template_id=req.template_id,
                        pool_state=PoolState.AVAILABLE,
                        page=1,
                        page_size=1000,
                    )
                ).sandboxes
                if available:
                    sandbox = available[0]
                    allocated = self.sandbox_service.mark_pool_allocated(
                        sandbox.id,
                        name=req.name,
                        metadata=req.metadata,
                        ttl_seconds=self._pool_ttl_seconds(req.template_id),
                    )
            finally:
                self._release_claim_lock(req.template_id, lock_value)
            # Dispatch events and check replenishment outside the lock to minimise hold time.
            if allocated is not None:
                sandbox_metrics.record_create(
                    template_id=req.template_id,
                    duration=time.perf_counter() - _t0,
                    success=True,
                    source="pool",
                )
                self.sandbox_service.dispatch_running_events(allocated.id)
                # We just consumed one AVAILABLE sandbox — replenishment is
                # almost certainly needed.  Skip the extra K8s list (_metrics)
                # and let reconcile_pool decide the exact delta itself.
                self._spawn_reconcile(req.template_id)
                return allocated

        # Pool 未命中或无 Pool → 直接创建（create_sandbox 内部已有埋点）
        sandbox = self.sandbox_service.create_sandbox(
            template_id=req.template_id,
            name=req.name,
            metadata=req.metadata,
            wait_ready=True,
            dispatch_events=True,
            ttl_seconds=self._pool_ttl_seconds(req.template_id),
        )
        if pool and pool.enabled:
            # Pool miss: we just bypassed the pool entirely.  Trigger reconcile
            # so it can top up the ready queue; no need to count first.
            self._spawn_reconcile(req.template_id)
        return sandbox

    def release_sandbox(self, sandbox_id: str) -> None:
        sandbox = self.sandbox_service.get_sandbox(sandbox_id)
        template_id = sandbox.template_id
        self.sandbox_service.delete_sandbox(sandbox_id)
        pool = self.repository.get(template_id)
        if pool and pool.enabled:
            # We just removed a sandbox from the pool — replenishment is very
            # likely needed.  Skip the extra K8s list and let reconcile_pool
            # compute the exact delta.
            self._spawn_reconcile(template_id)

    def renew_sandbox_ttl(self, sandbox_id: str, ttl: int) -> None:
        self.sandbox_service.renew_ttl(sandbox_id, ttl)

    def update_sandbox_ttl(self, sandbox_id: str, ttl_seconds: int) -> None:
        self.sandbox_service.update_ttl(sandbox_id, ttl_seconds)

    # ---- Reconcile (waterline) ----

    def reconcile_pool(self, template_id: str) -> None:
        created_ids = self._reconcile_create(template_id)
        self._reconcile_mark_ready(created_ids)
        metrics = self._reconcile_cleanup(template_id)
        # Re-trigger if max_creating truncated this round and we're still below target
        if created_ids:
            pool = self.repository.get(template_id)
            if pool and pool.enabled:
                if metrics["ready"] + metrics["creating"] < pool.target_ready:
                    self._spawn_reconcile(template_id)

    def _reconcile_create(self, template_id: str) -> list[str]:
        """Acquire lock, compute need, batch-create CREATING sandboxes, release lock."""
        lock_value = self._acquire_lock(template_id)
        if lock_value is None:
            return []
        try:
            pool = self.repository.get(template_id)
            if pool is None or not pool.enabled or pool.min_ready <= 0:
                return []

            # Fetch once inside the lock so metrics and create decision are consistent.
            all_sandboxes = self.sandbox_service.list_sandboxes(
                QueryOptions(template_id=template_id, page=1, page_size=1000)
            ).sandboxes
            metrics = self._metrics_from_list(all_sandboxes)
            effective_supply = metrics["ready"] + metrics["creating"]
            if effective_supply >= pool.target_ready:
                return []
            need = pool.target_ready - effective_supply
            need = min(need, pool.max_creating - metrics["creating"])
            need = max(need, 0)

            created_ids: list[str] = []
            for _ in range(need):
                try:
                    sandbox = self.sandbox_service.create_sandbox(
                        template_id=template_id,
                        metadata={"pool-managed": "true"},
                        pool_state=PoolState.CREATING,
                        wait_ready=False,
                        dispatch_events=False,
                        ttl_seconds=0,
                    )
                    created_ids.append(sandbox.id)
                except Exception:  # noqa: BLE001
                    logger.exception("failed to create pool sandbox for %s", template_id)
            return created_ids
        finally:
            self._release_lock(template_id, lock_value)

    def _reconcile_mark_ready(self, sandbox_ids: list[str]) -> None:
        """Wait for each CREATING sandbox to become ready, then mark AVAILABLE.

        Sandboxes are waited in parallel so a slow pod does not block the others.
        """
        if not sandbox_ids:
            return

        def _wait_one(sandbox_id: str) -> None:
            try:
                self.sandbox_service.gateway.wait_for_pod_ready(
                    f"app={sandbox_id},component=sandbox"
                )
                lock_value = self._acquire_claim_lock(
                    self.sandbox_service.get_sandbox(sandbox_id).template_id
                )
                if lock_value is None:
                    raise RuntimeError(f"timed out acquiring pool claim lock for sandbox {sandbox_id}")
                try:
                    sandbox = self.sandbox_service.get_sandbox(sandbox_id)
                    pool = self.repository.get(sandbox.template_id)
                    if sandbox.terminating:
                        return
                    if pool is None or not pool.enabled:
                        self.sandbox_service.delete_sandbox(sandbox_id)
                        return
                    if sandbox.pool_state == PoolState.CREATING:
                        self.sandbox_service.update_pool_state(sandbox_id, PoolState.AVAILABLE)
                finally:
                    self._release_claim_lock(sandbox.template_id, lock_value)
            except Exception:  # noqa: BLE001
                logger.exception("pool sandbox %s failed to become ready", sandbox_id)
                try:
                    self.sandbox_service.update_pool_state(sandbox_id, PoolState.FAILED)
                except Exception:  # noqa: BLE001
                    pass

        max_workers = min(len(sandbox_ids), 10)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_wait_one, sid): sid for sid in sandbox_ids}
            for future in as_completed(futures):
                sid = futures[future]
                exc = future.exception()
                if exc:
                    logger.error("unexpected error waiting for pool sandbox %s: %s", sid, exc)

    def _reconcile_cleanup(self, template_id: str) -> dict[str, int]:
        """Scale down excess AVAILABLE sandboxes and clean up FAILED ones.

        Returns the pool metrics computed from the snapshot taken at the start of
        this call so that callers can reuse it without issuing another K8s list.
        """
        pool = self.repository.get(template_id)
        if pool is None:
            return self._metrics_from_list([])
        # Fetch sandboxes once and derive metrics + candidates from the same snapshot.
        all_sandboxes = self.sandbox_service.list_sandboxes(
            QueryOptions(template_id=template_id, page=1, page_size=1000)
        ).sandboxes
        metrics = self._metrics_from_list(all_sandboxes)
        if metrics["ready"] > pool.target_ready:
            extra = metrics["ready"] - pool.target_ready
            candidates = [s for s in all_sandboxes if s.pool_state == PoolState.AVAILABLE][:extra]
            for sandbox in candidates:
                try:
                    self.sandbox_service.delete_sandbox(sandbox.id)
                    metrics["ready"] -= 1
                except Exception:  # noqa: BLE001
                    pass
        failed_sandboxes = [s for s in all_sandboxes if s.pool_state == PoolState.FAILED]
        for sandbox in failed_sandboxes:
            try:
                self.sandbox_service.delete_sandbox(sandbox.id)
                metrics["failed"] -= 1
            except Exception:  # noqa: BLE001
                pass
        return metrics

    # ---- Metrics ----

    def _metrics(self, template_id: str) -> dict[str, int]:
        sandboxes = self.sandbox_service.list_sandboxes(
            QueryOptions(template_id=template_id, page=1, page_size=1000)
        ).sandboxes
        return self._metrics_from_list(sandboxes)

    @staticmethod
    def _metrics_from_list(sandboxes: list) -> dict[str, int]:
        metrics = {"ready": 0, "creating": 0, "allocated": 0, "failed": 0, "terminating": 0}
        for sandbox in sandboxes:
            if sandbox.terminating:
                metrics["terminating"] += 1
                continue
            if sandbox.pool_state == PoolState.AVAILABLE:
                metrics["ready"] += 1
            elif sandbox.pool_state == PoolState.CREATING:
                metrics["creating"] += 1
            elif sandbox.pool_state == PoolState.ALLOCATED:
                metrics["allocated"] += 1
            elif sandbox.pool_state == PoolState.FAILED:
                metrics["failed"] += 1
        return metrics
