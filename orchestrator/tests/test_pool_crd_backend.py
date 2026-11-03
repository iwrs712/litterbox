from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace

from kubernetes.client import ApiException
import pytest

from orchestrator.config import Settings
from orchestrator.domain.models import (
    AllocateSandboxRequest,
    CreatePoolRequest,
    Pool,
    Template,
    UpdatePoolRequest,
    WorkspaceConfig,
)
from orchestrator.infra.sandbox_pool_crd import SandboxPoolRepository
from orchestrator.services.pools import PoolService
from orchestrator.services.sandbox_crd import SandboxCRDService
from orchestrator.utils import utcnow


def _merge(target: dict, patch: dict) -> None:
    for key, value in patch.items():
        if value is None:
            target.pop(key, None)
        elif isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge(target[key], value)
        else:
            target[key] = deepcopy(value)


class FakePoolApi:
    def __init__(self) -> None:
        self.objects: dict[str, dict] = {}
        self.patches: list[tuple[str, dict]] = []

    def create_namespaced_custom_object(self, group, version, namespace, plural, body):
        name = body["metadata"]["name"]
        if name in self.objects:
            raise ApiException(status=409, reason="AlreadyExists")
        obj = deepcopy(body)
        obj["metadata"]["creationTimestamp"] = utcnow().isoformat()
        self.objects[name] = obj
        return deepcopy(obj)

    def get_namespaced_custom_object(self, group, version, namespace, plural, name):
        if name not in self.objects:
            raise ApiException(status=404, reason="NotFound")
        return deepcopy(self.objects[name])

    def list_namespaced_custom_object(self, group, version, namespace, plural, label_selector=None):
        return {"items": [deepcopy(obj) for obj in self.objects.values()]}

    def patch_namespaced_custom_object(self, group, version, namespace, plural, name, body):
        self.patches.append((name, deepcopy(body)))
        if name not in self.objects:
            raise ApiException(status=404, reason="NotFound")
        obj = self.objects[name]
        _merge(obj, body)
        return deepcopy(obj)

    def delete_namespaced_custom_object(self, group, version, namespace, plural, name, body=None):
        self.objects.pop(name, None)


def settings() -> Settings:
    return Settings.model_validate(
        {
            "kubernetes": {"runtime_class": "kata-clh", "image_pull_secret": ""},
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


def template() -> Template:
    now = utcnow()
    return Template(
        id="ubuntu",
        name="ubuntu",
        image="ubuntu:22.04",
        command="sleep infinity",
        env=["BASE=1"],
        cpu_millicores=500,
        memory_mb=512,
        ttl_seconds=600,
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


class FakeGateway:
    namespace = "default"
    available_runtime_classes = {"kata-clh"}

    @staticmethod
    def secret_exists(_name: str) -> bool:
        return False


class FakeSandboxCRDGateway:
    namespace = "default"
    group = "litterbox.io"
    version = "v1alpha1"
    plural = "sandboxes"

    def __init__(self) -> None:
        self.objects: dict[str, dict] = {}

    def list(self, label_selector: str = ""):
        return [deepcopy(obj) for obj in self.objects.values()]

    def patch_json(self, name: str, operations: list[dict]):
        obj = self.objects[name]
        if operations and operations[0]["op"] == "test":
            if obj["metadata"].get("resourceVersion") != operations[0]["value"]:
                raise ApiException(status=409, reason="Conflict")
        if name == "conflict":
            raise ApiException(status=409, reason="Conflict")
        for op in operations:
            if op["op"] == "test":
                continue
            path = op["path"]
            if path == "/metadata/labels":
                obj["metadata"]["labels"] = deepcopy(op["value"])
            elif path == "/metadata/annotations":
                obj["metadata"]["annotations"] = deepcopy(op["value"])
            elif path == "/metadata/ownerReferences":
                obj["metadata"]["ownerReferences"] = deepcopy(op["value"])
            elif path == "/spec/state":
                obj["spec"]["state"] = op["value"]
            elif path == "/spec/ttlSeconds":
                obj["spec"]["ttlSeconds"] = op["value"]
            elif path == "/spec/ttlAnchor" and op["op"] == "remove":
                obj["spec"].pop("ttlAnchor", None)
            elif path == "/spec/ttlAnchor":
                obj["spec"]["ttlAnchor"] = op["value"]
        return deepcopy(obj)

    def patch(self, name: str, body: dict):
        _merge(self.objects[name], body)
        return deepcopy(self.objects[name])

    def delete(self, name: str) -> None:
        self.objects.pop(name, None)


def sandbox_cr(name: str, resource_version: str) -> dict:
    return {
        "apiVersion": "litterbox.io/v1alpha1",
        "kind": "Sandbox",
        "metadata": {
            "name": name,
            "namespace": "default",
            "resourceVersion": resource_version,
            "creationTimestamp": utcnow().isoformat(),
            "labels": {
                "component": "sandbox",
                "litterbox.io/template-id": "ubuntu",
                "litterbox.io/pool": "ubuntu",
                "litterbox.io/pool-state": "available",
            },
            "annotations": {"litterbox.io/workspace-config": resolved_workspace().model_dump_json()},
            "ownerReferences": [{"kind": "SandboxPool", "name": "ubuntu"}],
        },
        "spec": {
            "templateID": "ubuntu",
            "image": "ubuntu:22.04",
            "resources": {"limits": {"cpu": "500m", "memory": "512Mi"}},
            "workspace": {
                "enabled": True,
                "mountPath": "/workspace",
                "size": "1Gi",
                "storageClassName": "local-path",
                "claimName": f"workspace-{name}",
            },
            "envd": {"enabled": True},
            "lifecycle": {},
            "state": "Running",
            "ttlSeconds": 0,
        },
        "status": {"phase": "Running", "podIP": "10.0.0.1"},
    }


def test_build_pool_template_strips_identity_and_ttl() -> None:
    service = SandboxCRDService(settings(), FakeGateway(), FakeSandboxCRDGateway())

    spec = service.build_pool_template(template=template(), workspace=resolved_workspace())

    assert spec["workspace"]["claimName"] == ""
    assert spec["ttlSeconds"] == 0
    assert "ttlAnchor" not in spec
    assert spec["state"] == "Running"
    assert {"name": "BASE", "value": "1"} in spec["env"]
    assert spec["envd"]["enabled"] is True


def test_claim_available_retries_conflicts_and_detaches_owner() -> None:
    crd = FakeSandboxCRDGateway()
    crd.objects["conflict"] = sandbox_cr("conflict", "1")
    crd.objects["winner"] = sandbox_cr("winner", "2")
    service = SandboxCRDService(settings(), FakeGateway(), crd)

    claimed = service.claim_available(
        "ubuntu",
        name="demo",
        metadata={"user_id": "u-1"},
        ttl_seconds=60,
    )

    assert claimed is not None
    assert claimed.id == "winner"
    winner = crd.objects["winner"]
    assert winner["metadata"]["labels"]["litterbox.io/pool-state"] == "allocated"
    assert winner["metadata"]["labels"]["litterbox.io/user-user_id"] == "u-1"
    assert winner["metadata"]["annotations"]["litterbox.io/allocated-name"] == "demo"
    assert winner["metadata"]["ownerReferences"] == []
    assert winner["spec"]["ttlSeconds"] == 60
    assert winner["spec"]["ttlAnchor"]
    assert crd.objects["conflict"]["metadata"]["labels"]["litterbox.io/pool-state"] == "available"


def test_pool_repository_roundtrip_and_status() -> None:
    api = FakePoolApi()
    repository = SandboxPoolRepository(FakeGateway(), settings(), api=api)
    now = datetime.now(tz=UTC)
    pool = Pool(
        template_id="ubuntu",
        enabled=True,
        min_ready=1,
        target_ready=2,
        max_creating=5,
        sandbox_template={"templateID": "ubuntu"},
        created_at=now,
        updated_at=now,
    )

    repository.save(pool)
    loaded = repository.get("ubuntu")

    assert loaded is not None
    assert loaded.target_ready == 2
    assert loaded.sandbox_template == {"templateID": "ubuntu"}
    api.objects["ubuntu"]["status"] = {"ready": 2, "creating": 0, "allocated": 1}
    assert repository.get_status("ubuntu")["ready"] == 2

    repository.request_reconcile("ubuntu")
    assert "litterbox.io/reconcile-requested-at" in api.objects["ubuntu"]["metadata"]["annotations"]

    repository.delete("ubuntu")
    assert repository.get("ubuntu") is None


class FakePoolRepository:
    def __init__(self) -> None:
        self.pools: dict[str, Pool] = {}
        self.status: dict[str, dict] = {}
        self.reconcile_requests: list[str] = []
        self.deleted: list[str] = []

    def get(self, template_id: str):
        return self.pools.get(template_id)

    def save(self, pool: Pool) -> Pool:
        self.pools[pool.template_id] = pool
        return pool

    def list(self):
        return list(self.pools.values())

    def get_status(self, template_id: str):
        return self.status.get(template_id, {})

    def delete(self, template_id: str) -> None:
        self.deleted.append(template_id)
        self.pools.pop(template_id, None)

    def request_reconcile(self, template_id: str) -> None:
        self.reconcile_requests.append(template_id)


class FakeSandboxService:
    def __init__(self) -> None:
        self.claimed = False
        self.created: list[dict] = []
        self.dispatched: list[str] = []
        self.detached: list[str] = []
        self.settings = settings()

    def get_template(self, _template_id: str) -> Template:
        return template()

    def _resolve_workspace(self, _template, _override):
        return resolved_workspace()

    def build_pool_template(self, _template, _workspace):
        return {"templateID": "ubuntu"}

    def claim_pool_sandbox(self, **kwargs):
        if not self.claimed:
            return None
        return SimpleNamespace(id="claimed", template_id="ubuntu")

    def create_sandbox(self, **kwargs):
        self.created.append(kwargs)
        return SimpleNamespace(id="direct", template_id="ubuntu")

    def dispatch_running_events(self, sandbox_id: str) -> None:
        self.dispatched.append(sandbox_id)

    def detach_pool_sandboxes(self, pool_name: str) -> None:
        self.detached.append(pool_name)


def build_pool_service() -> tuple[PoolService, FakePoolRepository, FakeSandboxService]:
    repository = FakePoolRepository()
    sandbox_service = FakeSandboxService()
    return (
        PoolService(repository, sandbox_service, SimpleNamespace(get_template=lambda _id: template())),
        repository,
        sandbox_service,
    )


def test_pool_create_update_delete() -> None:
    service, repository, sandbox_service = build_pool_service()

    status = service.create_pool("ubuntu", CreatePoolRequest(min_ready=2))
    assert status.target_ready == 2
    assert repository.pools["ubuntu"].sandbox_template == {"templateID": "ubuntu"}

    updated = service.update_pool("ubuntu", UpdatePoolRequest(min_ready=0))
    assert updated.enabled is False
    assert updated.target_ready == 0

    service.delete_pool("ubuntu")
    assert sandbox_service.detached == ["ubuntu"]
    assert repository.deleted == ["ubuntu"]


def test_allocate_prefers_pool_then_falls_back_to_direct_create() -> None:
    service, repository, sandbox_service = build_pool_service()
    service.create_pool("ubuntu", CreatePoolRequest(min_ready=1))

    sandbox_service.claimed = True
    claimed = service.allocate_sandbox(AllocateSandboxRequest(template_id="ubuntu"))
    assert claimed.id == "claimed"
    assert sandbox_service.dispatched == ["claimed"]
    assert sandbox_service.created == []

    sandbox_service.claimed = False
    direct = service.allocate_sandbox(AllocateSandboxRequest(template_id="ubuntu"))
    assert direct.id == "direct"
    assert sandbox_service.created[0]["template_id"] == "ubuntu"
    assert repository.reconcile_requests == ["ubuntu"]


def test_allocate_rejects_overrides_with_warm_pool() -> None:
    service, _, _ = build_pool_service()
    service.create_pool("ubuntu", CreatePoolRequest(min_ready=1))

    with pytest.raises(ValueError, match="env override is not supported"):
        service.allocate_sandbox(
            AllocateSandboxRequest(template_id="ubuntu", env=["A=1"])
        )
    with pytest.raises(ValueError, match="workspace override is not supported"):
        service.allocate_sandbox(
            AllocateSandboxRequest(
                template_id="ubuntu",
                workspace={"size": "2Gi"},
            )
        )
