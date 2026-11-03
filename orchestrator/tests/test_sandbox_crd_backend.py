from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

from kubernetes.client import ApiException
import pytest

from orchestrator.config import Settings
from orchestrator.domain.models import (
    HostPathMount,
    SandboxLifecycle,
    SandboxStatus,
    Template,
    WorkspaceConfig,
)
from orchestrator.services.sandbox_crd import SandboxCRDService
from orchestrator.services.sandboxes import SandboxService
from orchestrator.utils import utcnow


def _merge(target: dict, patch: dict) -> None:
    for key, value in patch.items():
        if value is None:
            target.pop(key, None)
        elif isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge(target[key], value)
        else:
            target[key] = deepcopy(value)


class FakeCRDGateway:
    namespace = "default"
    group = "litterbox.io"
    version = "v1alpha1"
    plural = "sandboxes"

    def __init__(self) -> None:
        self.objects: dict[str, dict] = {}
        self.patches: list[tuple[str, dict]] = []

    def create(self, body: dict) -> dict:
        obj = deepcopy(body)
        obj.setdefault("metadata", {})["creationTimestamp"] = utcnow().isoformat()
        obj.setdefault("status", {"phase": "Pending"})
        self.objects[obj["metadata"]["name"]] = obj
        return deepcopy(obj)

    def get(self, name: str) -> dict:
        if name not in self.objects:
            raise ApiException(status=404, reason="Not Found")
        return deepcopy(self.objects[name])

    def list(self, label_selector: str = "") -> list[dict]:
        return [deepcopy(obj) for obj in self.objects.values()]

    def patch(self, name: str, body: dict) -> dict:
        self.patches.append((name, deepcopy(body)))
        obj = self.objects[name]
        _merge(obj, body)
        return deepcopy(obj)

    def delete(self, name: str, grace_period_seconds: int = 0) -> None:
        self.objects.pop(name, None)

    def wait_until_phase(self, name: str, phases: set[str], **kwargs) -> dict:
        obj = self.objects[name]
        state = (obj.get("spec") or {}).get("state")
        obj.setdefault("status", {})["phase"] = "Paused" if state == "Paused" else "Running"
        return deepcopy(obj)


class FakeGateway:
    namespace = "default"

    def __init__(self) -> None:
        self.available_runtime_classes = {"kata-clh"}
        self.deleted_claims: list[str] = []
        self.ready_selectors: list[str] = []
        self.pod = SimpleNamespace(
            metadata=SimpleNamespace(name="pod-1"),
            status=SimpleNamespace(pod_ip="10.42.0.9"),
            spec=SimpleNamespace(node_name="node-1"),
        )

    def secret_exists(self, name: str) -> bool:
        return False

    def wait_for_pod_ready(self, label_selector: str, timeout_seconds: int = 120):
        self.ready_selectors.append(label_selector)
        return self.pod

    def list_services(self, _label_selector: str):
        return []

    def delete_persistent_volume_claim(self, name: str) -> None:
        self.deleted_claims.append(name)


class FakeTemplateService:
    def __init__(self, template: Template) -> None:
        self.template = template

    def get_template(self, template_id: str) -> Template:
        if template_id != self.template.id:
            raise KeyError(template_id)
        return self.template


class RecordingDispatcher:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def dispatch(self, **kwargs) -> None:
        self.events.append(kwargs)


def crd_settings() -> Settings:
    return Settings.model_validate(
        {
            "kubernetes": {"runtime_class": "kata-clh", "image_pull_secret": "pull-secret"},
            "sandbox": {"backend": "crd"},
            "workspace": {
                "enabled": True,
                "mount_path": "/workspace",
                "default_size": "1Gi",
                "storage_class": "local-path",
            },
            "envd": {
                "enabled": True,
                "version": "0.1.0",
                "host_binary_path": "/opt/litterbox/bin/envd",
                "container_binary_path": "/opt/litterbox/envd/envd",
                "port": 49983,
            },
        }
    )


def sample_template(ttl_seconds: int | None = 600) -> Template:
    now = utcnow()
    return Template(
        id="ubuntu",
        name="ubuntu",
        image="ubuntu:22.04",
        command="sleep infinity",
        env=["BASE=1", "SHARED=template"],
        cpu_millicores=500,
        memory_mb=512,
        ttl_seconds=ttl_seconds,
        created_at=now,
        updated_at=now,
    )


def resolved_workspace() -> WorkspaceConfig:
    return WorkspaceConfig(
        enabled=True,
        mount_path="/workspace",
        size="1Gi",
        storage_class="local-path",
    )


def build_crd_service(
    *,
    template: Template | None = None,
    fake_crd: FakeCRDGateway | None = None,
    gateway: FakeGateway | None = None,
) -> tuple[SandboxCRDService, FakeCRDGateway, FakeGateway]:
    crd = fake_crd or FakeCRDGateway()
    kube = gateway or FakeGateway()
    service = SandboxCRDService(crd_settings(), kube, crd)
    return service, crd, kube


def build_sandbox_service(
    *,
    template: Template | None = None,
    fake_crd: FakeCRDGateway | None = None,
    gateway: FakeGateway | None = None,
) -> tuple[SandboxService, FakeCRDGateway, FakeGateway, RecordingDispatcher]:
    template = template or sample_template()
    crd = fake_crd or FakeCRDGateway()
    kube = gateway or FakeGateway()
    dispatcher = RecordingDispatcher()
    service = object.__new__(SandboxService)
    service.gateway = kube
    service.template_service = FakeTemplateService(template)
    service.webhook_dispatcher = dispatcher
    service.settings = crd_settings()
    service.expose_service = None
    service.crd = SandboxCRDService(service.settings, kube, crd)
    return service, crd, kube, dispatcher


def test_build_object_compiles_template_into_spec() -> None:
    service, _, _ = build_crd_service()
    template = sample_template()
    body = service.build_object(
        sandbox_id="abc12345",
        template=template,
        metadata={"user_id": "u-1"},
        name="demo",
        env=["SHARED=override", "EXTRA=1"],
        pool_state="none",
        ttl_seconds=600,
        workspace=resolved_workspace(),
    )

    metadata = body["metadata"]
    spec = body["spec"]
    assert metadata["name"] == "abc12345"
    assert metadata["labels"]["component"] == "sandbox"
    assert metadata["labels"]["litterbox.io/user-user_id"] == "u-1"
    assert metadata["annotations"]["litterbox.io/allocated-name"] == "demo"
    assert spec["state"] == "Running"
    assert spec["ttlSeconds"] == 600
    assert spec["ttlAnchor"] is not None
    assert spec["command"] == ["sleep", "infinity"]
    assert {"name": "SHARED", "value": "override"} in spec["env"]
    assert {"name": "EXTRA", "value": "1"} in spec["env"]
    assert spec["workspace"]["claimName"] == "workspace-abc12345"
    assert spec["workspace"]["storageClassName"] == "local-path"
    assert spec["envd"]["enabled"] is True
    assert spec["lifecycle"]["postStart"][0] == "/opt/litterbox/envd/envd"
    assert spec["runtimeClassName"] == "kata-clh"
    assert spec["imagePullSecret"] == ""
    assert spec["nodeSelector"] == {"litterbox.io/envd-version": "0.1.0"}


def test_create_returns_domain_sandbox_and_writes_cr() -> None:
    service, crd, _ = build_crd_service()
    sandbox = service.create(
        sandbox_id="abc12345",
        template=sample_template(),
        metadata={},
        name="",
        env=None,
        pool_state="none",
        ttl_seconds=600,
        workspace=resolved_workspace(),
    )

    assert "abc12345" in crd.objects
    assert sandbox.id == "abc12345"
    assert sandbox.status == SandboxStatus.CREATED
    assert sandbox.ttl_seconds == 600
    assert sandbox.expires_at is not None
    assert sandbox.workspace == resolved_workspace()


def test_to_sandbox_maps_paused_and_locked_state() -> None:
    service, crd, _ = build_crd_service()
    anchor = utcnow() - timedelta(minutes=5)
    crd.objects["paused"] = {
        "apiVersion": "litterbox.io/v1alpha1",
        "kind": "Sandbox",
        "metadata": {
            "name": "paused",
            "namespace": "default",
            "creationTimestamp": anchor.isoformat(),
            "labels": {
                "litterbox.io/template-id": "ubuntu",
                "litterbox.io/pool-state": "allocated",
                "litterbox.io/user-tenant": "t-1",
            },
            "annotations": {
                "litterbox.io/resume-locked": "true",
                "litterbox.io/allocated-name": "demo",
            },
        },
        "spec": {
            "ttlSeconds": 60,
            "ttlAnchor": anchor.isoformat(),
            "state": "Running",
        },
        "status": {"phase": "Paused", "pausedReason": "TTLExpired"},
    }

    sandbox = service.get("paused")

    assert sandbox.status == SandboxStatus.STOPPED
    assert sandbox.locked is True
    assert sandbox.pool_state == "allocated"
    assert sandbox.metadata == {"tenant": "t-1"}
    assert sandbox.name == "demo"
    assert sandbox.expires_at == anchor + timedelta(seconds=60)


def test_suspend_and_resume_patch_desired_state() -> None:
    service, crd, _ = build_crd_service()
    service.create(
        sandbox_id="abc12345",
        template=sample_template(),
        metadata={},
        name="",
        env=None,
        pool_state="none",
        ttl_seconds=600,
        workspace=resolved_workspace(),
    )

    service.suspend("abc12345", ttl_expired=True)
    assert crd.objects["abc12345"]["spec"]["state"] == "Paused"
    assert "litterbox.io/ttl-suspended-at" in crd.objects["abc12345"]["metadata"]["annotations"]

    service.resume("abc12345", ttl_seconds=600)
    resumed = crd.objects["abc12345"]
    assert resumed["spec"]["state"] == "Running"
    assert resumed["spec"]["ttlAnchor"] is not None
    assert "litterbox.io/ttl-suspended-at" not in resumed["metadata"]["annotations"]


def test_set_ttl_and_renew_move_the_anchor() -> None:
    service, crd, _ = build_crd_service()
    service.create(
        sandbox_id="abc12345",
        template=sample_template(),
        metadata={},
        name="",
        env=None,
        pool_state="none",
        ttl_seconds=600,
        workspace=resolved_workspace(),
    )
    first_anchor = crd.objects["abc12345"]["spec"]["ttlAnchor"]

    service.set_ttl("abc12345", 60)
    assert crd.objects["abc12345"]["spec"]["ttlSeconds"] == 60
    assert crd.objects["abc12345"]["spec"]["ttlAnchor"] is not None

    service.renew_ttl("abc12345", ttl_seconds=120, current_ttl=60)
    renewed = crd.objects["abc12345"]["spec"]
    assert renewed["ttlSeconds"] == 60
    assert renewed["ttlAnchor"] != first_anchor

    service.set_ttl("abc12345", 0)
    assert crd.objects["abc12345"]["spec"]["ttlSeconds"] == 0
    assert crd.objects["abc12345"]["spec"].get("ttlAnchor") is None


def test_delete_removes_cr_and_leaves_pvc_to_garbage_collection() -> None:
    service, crd, kube, _ = build_sandbox_service()
    service.create_sandbox(template_id="ubuntu", ttl_seconds=600)

    sandbox_id = next(iter(crd.objects))
    service.delete_sandbox(sandbox_id)

    assert sandbox_id not in crd.objects
    assert kube.deleted_claims == []


def test_create_sandbox_sets_running_status_and_dispatches_events() -> None:
    service, crd, kube, dispatcher = build_sandbox_service()
    crd.objects.clear()

    response = service.create_sandbox(template_id="ubuntu", ttl_seconds=600)

    assert response.id in crd.objects
    assert response.status == SandboxStatus.RUNNING
    assert kube.ready_selectors == [f"app={response.id},component=sandbox"]
    assert [event["event"].value for event in dispatcher.events] == [
        "sandbox_started",
        "sandbox_ready",
    ]


def test_suspend_resume_and_status_counts() -> None:
    service, crd, _, _ = build_sandbox_service()
    first = service.create_sandbox(template_id="ubuntu", ttl_seconds=600)
    second = service.create_sandbox(template_id="ubuntu", ttl_seconds=600)

    suspended = service.suspend_sandbox(first.id)
    assert suspended.status == SandboxStatus.STOPPED
    assert crd.objects[first.id]["spec"]["state"] == "Paused"
    assert service.status_counts() == {
        "total": 2,
        "running": 1,
        "stopped": 1,
        "creating": 0,
    }

    resumed = service.resume_sandbox(first.id)
    assert resumed.status == SandboxStatus.RUNNING
    assert crd.objects[first.id]["spec"]["state"] == "Running"
    assert service.status_counts()["running"] == 2

    service.delete_sandbox(second.id)
    assert second.id not in crd.objects


def test_lock_and_unlock() -> None:
    service, crd, _, _ = build_sandbox_service()
    sandbox = service.create_sandbox(template_id="ubuntu", ttl_seconds=600)

    service.lock_sandbox(sandbox.id)
    assert service.get_sandbox(sandbox.id).locked is True
    with pytest.raises(Exception, match="locked"):
        service.resume_sandbox(sandbox.id)

    service.unlock_sandbox(sandbox.id)
    assert service.get_sandbox(sandbox.id).locked is False
    assert service.resume_sandbox(sandbox.id).status == SandboxStatus.RUNNING


def test_envd_disabled_preserves_template_lifecycle() -> None:
    settings = crd_settings()
    settings.envd.enabled = False
    crd = FakeCRDGateway()
    service = SandboxCRDService(settings, FakeGateway(), crd)
    template = sample_template()
    template.lifecycle = SandboxLifecycle.model_validate(
        {
            "postStart": {"exec": {"command": ["/bin/true"]}},
            "preStop": {
                "exec": {"command": ["/bin/false"]},
                "terminationGracePeriodSeconds": 20,
            },
        }
    )

    body = service.build_object(
        sandbox_id="abc12345",
        template=template,
        metadata={},
        name="",
        env=None,
        pool_state="none",
        ttl_seconds=600,
        workspace=resolved_workspace(),
    )

    assert body["spec"]["envd"]["enabled"] is False
    assert body["spec"]["lifecycle"]["postStart"] == ["/bin/true"]
    assert body["spec"]["lifecycle"]["preStop"] == ["/bin/false"]
    assert body["spec"]["lifecycle"]["terminationGracePeriodSeconds"] == 20


def test_envd_injection_rejects_template_post_start() -> None:
    service, _, _ = build_crd_service()
    template = sample_template()
    template.lifecycle = SandboxLifecycle.model_validate(
        {"postStart": {"exec": {"command": ["/bin/true"]}}}
    )

    with pytest.raises(ValueError, match="conflicts with envd injection"):
        service.build_object(
            sandbox_id="abc12345",
            template=template,
            metadata={},
            name="",
            env=None,
            pool_state="none",
            ttl_seconds=600,
            workspace=resolved_workspace(),
        )


def test_workspace_disabled_and_host_mounts() -> None:
    service, _, _ = build_crd_service()
    template = sample_template()
    template.host_path_mounts = [
        HostPathMount(host_path="/data", container_path="/mnt/data", read_only=True)
    ]
    workspace = resolved_workspace().model_copy(update={"enabled": False})

    body = service.build_object(
        sandbox_id="abc12345",
        template=template,
        metadata={},
        name="",
        env=None,
        pool_state="none",
        ttl_seconds=600,
        workspace=workspace,
    )

    assert body["spec"]["workspace"]["enabled"] is False
    assert body["spec"]["hostPathMounts"] == [
        {"hostPath": "/data", "containerPath": "/mnt/data", "readOnly": True}
    ]


def test_resume_rejects_locked_sandbox() -> None:
    service, crd, _, _ = build_sandbox_service()
    service.crd.create(
        sandbox_id="locked",
        template=sample_template(),
        metadata={},
        name="",
        env=None,
        pool_state="none",
        ttl_seconds=600,
        workspace=resolved_workspace(),
    )
    service.crd.lock("locked")

    with pytest.raises(Exception) as exc:
        service.resume_sandbox("locked")

    assert "locked" in str(exc.value)
