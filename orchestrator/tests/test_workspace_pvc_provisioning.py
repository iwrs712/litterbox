from __future__ import annotations

from types import SimpleNamespace

import pytest

from orchestrator.config import Settings
from orchestrator.domain.models import Template, utcnow
from orchestrator.services.sandboxes import SandboxService


def test_workspace_default_size_is_one_gib() -> None:
    assert Settings().workspace.default_size == "1Gi"


class RecordingGateway:
    namespace = "default"
    available_runtime_classes: set[str] = set()

    def __init__(self, *, fail_deployment: bool = False) -> None:
        self.events: list[str] = []
        self.fail_deployment = fail_deployment
        self.created_claim = None

    def secret_exists(self, _name: str) -> bool:
        return False

    def create_persistent_volume_claim(self, claim) -> None:
        self.events.append("pvc")
        self.created_claim = claim

    def create_deployment(self, _deployment) -> None:
        self.events.append("deployment")
        if self.fail_deployment:
            raise RuntimeError("deployment create failed")

    def delete_persistent_volume_claim(self, _name: str) -> None:
        self.events.append("delete-pvc")


def build_provisioning_service(
    *,
    fail_deployment: bool = False,
) -> tuple[SandboxService, RecordingGateway]:
    now = utcnow()
    template = Template(
        id="tpl-workspace",
        name="Workspace template",
        image="busybox:1.37",
        cpu_millicores=100,
        memory_mb=128,
        created_at=now,
        updated_at=now,
    )
    gateway = RecordingGateway(fail_deployment=fail_deployment)
    settings = Settings.model_validate(
        {
            "kubernetes": {"storage_class": "local-path"},
            "workspace": {"default_size": "1Gi"},
        }
    )
    service = SandboxService(
        gateway=gateway,
        template_service=SimpleNamespace(get_template=lambda _template_id: template),
        webhook_dispatcher=SimpleNamespace(),
        ttl_queue=SimpleNamespace(),
        settings=settings,
    )
    service.get_sandbox = lambda sandbox_id: SimpleNamespace(id=sandbox_id)
    return service, gateway


def test_create_sandbox_creates_workspace_pvc_before_deployment() -> None:
    service, gateway = build_provisioning_service()

    service.create_sandbox(
        template_id="tpl-workspace",
        wait_ready=False,
        dispatch_events=False,
    )

    assert gateway.events == ["pvc", "deployment"]
    claim = gateway.created_claim
    assert claim is not None
    assert claim.metadata.name.startswith("workspace-")
    assert claim.spec.access_modes == ["ReadWriteOnce"]
    assert claim.spec.volume_mode == "Filesystem"
    assert claim.spec.storage_class_name == "local-path"
    assert claim.spec.resources.requests == {"storage": "1Gi"}


def test_create_sandbox_deletes_new_workspace_pvc_when_deployment_creation_fails() -> None:
    service, gateway = build_provisioning_service(fail_deployment=True)

    with pytest.raises(RuntimeError, match="deployment create failed"):
        service.create_sandbox(
            template_id="tpl-workspace",
            wait_ready=False,
            dispatch_events=False,
        )

    assert gateway.events == ["pvc", "deployment", "delete-pvc"]
