from __future__ import annotations

from types import SimpleNamespace

import pytest

from orchestrator.config import Settings
from orchestrator.domain.models import Template, WorkspaceConfigOverride, utcnow
from orchestrator.services.sandboxes import SandboxService


def test_workspace_default_size_is_one_gib() -> None:
    assert Settings().workspace.default_size == "1Gi"


def test_workspace_mount_path_must_be_absolute() -> None:
    with pytest.raises(ValueError, match="workspace.mount_path must be an absolute path"):
        Settings.model_validate({"workspace": {"mount_path": "workspace"}})


def test_default_runtime_class_is_clh() -> None:
    assert Settings().kubernetes.runtime_class == "kata-clh"


class RecordingGateway:
    namespace = "default"
    available_runtime_classes: set[str] = set()

    def __init__(self, *, fail_deployment: bool = False) -> None:
        self.events: list[str] = []
        self.fail_deployment = fail_deployment
        self.created_claim = None
        self.created_deployment = None

    def secret_exists(self, _name: str) -> bool:
        return False

    def create_persistent_volume_claim(self, claim) -> None:
        self.events.append("pvc")
        self.created_claim = claim

    def create_deployment(self, deployment) -> None:
        self.events.append("deployment")
        self.created_deployment = deployment
        if self.fail_deployment:
            raise RuntimeError("deployment create failed")

    def delete_persistent_volume_claim(self, _name: str) -> None:
        self.events.append("delete-pvc")


def build_provisioning_service(
    *,
    fail_deployment: bool = False,
    workspace: dict | None = None,
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
            "workspace": {"default_size": "1Gi", **(workspace or {})},
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


def test_workspace_specific_storage_class_and_mount_path_override_legacy_settings() -> None:
    service, gateway = build_provisioning_service(
        workspace={
            "storage_class": "litterbox-workspace-lvm",
            "mount_path": "/data/workspace",
        }
    )

    service.create_sandbox(
        template_id="tpl-workspace",
        wait_ready=False,
        dispatch_events=False,
    )

    assert gateway.created_claim.spec.storage_class_name == "litterbox-workspace-lvm"
    container = gateway.created_deployment.spec.template.spec.containers[0]
    assert container.volume_mounts[0].mount_path == "/data/workspace"


def test_sandbox_workspace_override_wins_over_template_and_global_defaults() -> None:
    service, gateway = build_provisioning_service(
        workspace={
            "mount_path": "/global-workspace",
            "default_size": "1Gi",
            "storage_class": "global-storage",
        }
    )
    service.template_service.get_template = lambda _template_id: Template(
        id="tpl-workspace",
        name="Workspace template",
        image="busybox:1.37",
        cpu_millicores=100,
        memory_mb=128,
        workspace=WorkspaceConfigOverride(
            mount_path="/template-workspace",
            size="2Gi",
            storage_class="template-storage",
        ),
        created_at=utcnow(),
        updated_at=utcnow(),
    )

    service.create_sandbox(
        template_id="tpl-workspace",
        workspace=WorkspaceConfigOverride(
            mount_path="/sandbox-workspace",
            size="3Gi",
            storage_class="sandbox-storage",
        ),
        wait_ready=False,
        dispatch_events=False,
    )

    claim = gateway.created_claim
    container = gateway.created_deployment.spec.template.spec.containers[0]
    assert claim.spec.storage_class_name == "sandbox-storage"
    assert claim.spec.resources.requests == {"storage": "3Gi"}
    assert container.volume_mounts[0].mount_path == "/sandbox-workspace"
    assert gateway.created_deployment.metadata.annotations["litterbox.io/workspace-config"] == (
        '{"enabled":true,"mount_path":"/sandbox-workspace","size":"3Gi",'
        '"storage_class":"sandbox-storage"}'
    )


def test_workspace_can_be_disabled_without_creating_or_mounting_a_pvc() -> None:
    service, gateway = build_provisioning_service(workspace={"enabled": False})

    service.create_sandbox(
        template_id="tpl-workspace",
        wait_ready=False,
        dispatch_events=False,
    )

    assert gateway.events == ["deployment"]
    pod_spec = gateway.created_deployment.spec.template.spec
    assert pod_spec.volumes is None
    assert pod_spec.containers[0].volume_mounts is None


def test_create_sandbox_deletes_new_workspace_pvc_when_deployment_creation_fails() -> None:
    service, gateway = build_provisioning_service(fail_deployment=True)

    with pytest.raises(RuntimeError, match="deployment create failed"):
        service.create_sandbox(
            template_id="tpl-workspace",
            wait_ready=False,
            dispatch_events=False,
        )

    assert gateway.events == ["pvc", "deployment", "delete-pvc"]
