from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from orchestrator.config import Settings
from orchestrator.domain.models import (
    AllocateSandboxRequest,
    CreateTemplateRequest,
    Pool,
    Template,
    WorkspaceConfigOverride,
)
from orchestrator.services.pools import PoolService


def test_allocate_sandbox_rejects_env_when_pool_enabled() -> None:
    now = datetime.now(tz=UTC)
    pool = Pool(
        template_id="tpl-1",
        enabled=True,
        min_ready=1,
        target_ready=1,
        max_creating=1,
        created_at=now,
        updated_at=now,
    )

    service = object.__new__(PoolService)
    service.repository = SimpleNamespace(get=lambda _template_id: pool)

    request = AllocateSandboxRequest(template_id="tpl-1", env=["FEATURE_FLAG=true"])
    with pytest.raises(ValueError, match="env override is not supported"):
        service.allocate_sandbox(request)


def test_allocate_sandbox_rejects_workspace_override_when_pool_enabled() -> None:
    now = datetime.now(tz=UTC)
    pool = Pool(
        template_id="tpl-1",
        enabled=True,
        min_ready=1,
        target_ready=1,
        max_creating=1,
        created_at=now,
        updated_at=now,
    )
    service = object.__new__(PoolService)
    service.repository = SimpleNamespace(get=lambda _template_id: pool)

    request = AllocateSandboxRequest(
        template_id="tpl-1",
        workspace=WorkspaceConfigOverride(size="2Gi"),
    )
    with pytest.raises(ValueError, match="workspace override is not supported"):
        service.allocate_sandbox(request)


def test_allocate_sandbox_passes_env_to_direct_create() -> None:
    class DummySandboxService:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def create_sandbox(self, **kwargs):
            self.calls.append(kwargs)
            return "created"

    sandbox_service = DummySandboxService()

    service = object.__new__(PoolService)
    service.repository = SimpleNamespace(get=lambda _template_id: None)
    service.sandbox_service = sandbox_service
    service._pool_ttl_seconds = lambda _template_id: 120

    request = AllocateSandboxRequest(
        template_id="tpl-1",
        name="sbx",
        metadata={"user_id": "u-1"},
        env=["RUNTIME_TOKEN=abc"],
    )
    result = service.allocate_sandbox(request)

    assert result == "created"
    assert len(sandbox_service.calls) == 1
    assert sandbox_service.calls[0]["env"] == ["RUNTIME_TOKEN=abc"]


def test_template_ttl_allows_zero_but_rejects_negative() -> None:
    request = CreateTemplateRequest(
        name="template",
        image="busybox:latest",
        cpu_millicores=500,
        memory_mb=512,
        ttl_seconds=0,
    )

    assert request.ttl_seconds == 0

    with pytest.raises(ValueError, match="ttl_seconds"):
        CreateTemplateRequest(
            name="template",
            image="busybox:latest",
            cpu_millicores=500,
            memory_mb=512,
            ttl_seconds=-1,
        )


def test_pool_ttl_preserves_template_zero_ttl() -> None:
    now = datetime.now(tz=UTC)
    template = Template(
        id="tpl-zero-ttl",
        name="template",
        image="busybox:latest",
        cpu_millicores=500,
        memory_mb=512,
        ttl_seconds=0,
        created_at=now,
        updated_at=now,
    )

    service = object.__new__(PoolService)
    service.sandbox_service = SimpleNamespace(
        get_template=lambda _template_id: template,
        settings=Settings(),
    )

    assert service._pool_ttl_seconds("tpl-zero-ttl") == 0
