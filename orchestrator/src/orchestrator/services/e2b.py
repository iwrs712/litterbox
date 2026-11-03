from __future__ import annotations

from typing import Any

from orchestrator.config import Settings
from orchestrator.domain.e2b_models import (
    E2BConnectSandboxRequest,
    E2BCreateSandboxRequest,
    E2BSandboxCreateResponse,
    E2BSandboxDetail,
)
from orchestrator.domain.models import AllocateSandboxRequest, SandboxStatus
from orchestrator.services.pools import PoolService
from orchestrator.services.sandboxes import SandboxService


class E2BUnsupportedOperationError(RuntimeError):
    pass


class E2BControlPlaneService:
    def __init__(self, settings: Settings, sandbox_service: SandboxService, pool_service: PoolService) -> None:
        self.settings = settings
        self.sandbox_service = sandbox_service
        self.pool_service = pool_service

    def create(self, request: E2BCreateSandboxRequest) -> E2BSandboxCreateResponse:
        if request.allow_internet_access is False:
            raise E2BUnsupportedOperationError("network policy is not supported by the minimal E2B facade")

        env = [f"{key}={value}" for key, value in request.env_vars.items()]
        sandbox = self.pool_service.allocate_sandbox(
            AllocateSandboxRequest(
                template_id=request.template_id,
                metadata=request.metadata,
                env=env,
            )
        )
        if sandbox.ttl_seconds != request.timeout:
            self.sandbox_service.update_ttl(sandbox.id, request.timeout)
            sandbox = self.sandbox_service.get_sandbox(sandbox.id)
        return self._create_response(sandbox)

    def get(self, sandbox_id: str) -> E2BSandboxDetail:
        return self._detail(self.sandbox_service.get_sandbox(sandbox_id))

    def connect(self, sandbox_id: str, request: E2BConnectSandboxRequest) -> E2BSandboxCreateResponse:
        sandbox = self.sandbox_service.resume_sandbox(sandbox_id)
        self.sandbox_service.update_ttl(sandbox_id, request.timeout)
        return self._create_response(sandbox)

    def pause(self, sandbox_id: str, *, keep_memory: bool) -> None:
        if keep_memory:
            raise E2BUnsupportedOperationError(
                "memory snapshots are not supported; use pause(keep_memory=False)"
            )
        self.sandbox_service.suspend_sandbox(sandbox_id)

    def set_timeout(self, sandbox_id: str, timeout: int) -> None:
        self.sandbox_service.update_ttl(sandbox_id, timeout)

    def kill(self, sandbox_id: str) -> None:
        self.pool_service.release_sandbox(sandbox_id)

    def _create_response(self, sandbox: Any) -> E2BSandboxCreateResponse:
        envd_access_token = self.settings.e2b.api_key or self.settings.auth.bearer_token or None
        return E2BSandboxCreateResponse(
            templateID=sandbox.template_id,
            sandboxID=sandbox.id,
            clientID="litterbox",
            domain=self.settings.e2b.domain,
            envdVersion=self.settings.e2b.envd_version,
            envdAccessToken=envd_access_token,
            trafficAccessToken=None,
        )

    def _detail(self, sandbox: Any) -> E2BSandboxDetail:
        status = getattr(sandbox.status, "value", sandbox.status)
        state = {
            SandboxStatus.RUNNING.value: "running",
            SandboxStatus.STOPPED.value: "paused",
            SandboxStatus.EXITED.value: "dead",
        }.get(status, status)
        return E2BSandboxDetail(
            sandboxID=sandbox.id,
            templateID=sandbox.template_id,
            domain=self.settings.e2b.domain,
            state=state,
            metadata=sandbox.metadata,
            envdVersion=self.settings.e2b.envd_version,
            envdAccessToken=None,
            trafficAccessToken=None,
            startedAt=sandbox.created_at,
            endAt=sandbox.expires_at,
        )
