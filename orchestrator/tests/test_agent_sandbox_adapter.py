from __future__ import annotations

from types import SimpleNamespace

from orchestrator.config import Settings
from orchestrator.domain.models import SandboxStatus, Template, WorkspaceConfig
from orchestrator.infra.sandbox_pool_crd import SandboxPoolRepository
from orchestrator.services.sandbox_crd import SandboxCRDService


def settings() -> Settings:
    return Settings.model_validate(
        {
            "kubernetes": {
                "runtime_class": "kata-clh",
                "image_pull_secret": "",
                "namespace": "default",
            },
            "sandbox": {"ephemeral_storage_request": "256Mi", "ephemeral_storage_limit": "12Gi"},
            "workspace": {
                "enabled": True,
                "mount_path": "/workspace",
                "default_size": "1Gi",
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
    now = __import__("orchestrator.utils", fromlist=["utcnow"]).utcnow()
    return Template(
        id="ubuntu",
        name="ubuntu",
        image="ubuntu:24.04",
        command="sleep infinity",
        env=["BASE=1", "SHARED=template"],
        cpu_millicores=500,
        memory_mb=512,
        ttl_seconds=600,
        created_at=now,
        updated_at=now,
    )


def workspace() -> WorkspaceConfig:
    return WorkspaceConfig(enabled=True, mount_path="/workspace", size="1Gi")


class FakeGateway:
    namespace = "default"
    available_runtime_classes = {"kata-clh"}

    @staticmethod
    def secret_exists(_name: str) -> bool:
        return False


def service() -> SandboxCRDService:
    return SandboxCRDService(settings(), FakeGateway())


def test_pod_template_uses_empty_dir_envd_and_ephemeral_storage() -> None:
    pod = service().build_pod_template(template(), workspace())
    spec = pod["spec"]
    container = spec["containers"][0]

    assert spec["automountServiceAccountToken"] is False
    assert spec["runtimeClassName"] == "kata-clh"
    assert spec["nodeSelector"] == {"litterbox.io/envd-version": "0.1.0"}
    assert container["resources"]["limits"]["ephemeral-storage"] == "12Gi"
    assert any(v.get("emptyDir", {}).get("sizeLimit") == "1Gi" for v in spec["volumes"])
    assert not any("persistentVolumeClaim" in v for v in spec["volumes"])
    assert container["lifecycle"]["postStart"]["exec"]["command"][0] == (
        "/opt/litterbox/envd/envd"
    )
    assert container["securityContext"]["appArmorProfile"]["type"] == "Unconfined"


def test_claim_carries_env_ttl_and_pod_labels() -> None:
    claim = service().build_claim(
        sandbox_id="abc12345",
        template=template(),
        metadata={"user_id": "u-1"},
        name="agent",
        env=["RUNTIME=on"],
        pool_state="allocated",
        ttl_seconds=120,
        workspace=workspace(),
    )
    spec = claim["spec"]
    assert spec["warmPoolRef"]["name"] == "ubuntu"
    assert spec["env"] == [
        {"containerName": "main", "name": "RUNTIME", "value": "on"}
    ]
    assert spec["lifecycle"]["shutdownPolicy"] == "Delete"
    assert spec["additionalPodMetadata"]["labels"]["litterbox.io/sandbox-id"] == "abc12345"
    assert claim["metadata"]["labels"]["litterbox.io/pool-state"] == "allocated"


def test_to_sandbox_maps_running_and_paused() -> None:
    svc = service()
    claim = {
        "metadata": {
            "name": "abc12345",
            "labels": {
                "litterbox.io/template-id": "ubuntu",
                "litterbox.io/user-user_id": "u-1",
            },
            "annotations": {
                "litterbox.io/ttl-seconds": "120",
                "litterbox.io/ttl-anchor": "2026-01-01T00:00:00+00:00",
                "litterbox.io/workspace-config": workspace().model_dump_json(),
            },
            "creationTimestamp": "2026-01-01T00:00:00Z",
        },
        "spec": {},
        "status": {},
    }
    running = {
        "status": {
            "conditions": [
                {"type": "Suspended", "status": "False"},
                {"type": "Ready", "status": "True"},
            ],
            "podIPs": ["10.0.0.1"],
        }
    }
    paused = {
        "status": {
            "conditions": [
                {"type": "Suspended", "status": "True"},
                {"type": "Ready", "status": "False"},
            ]
        }
    }

    assert svc.to_sandbox(claim, running).status == SandboxStatus.RUNNING
    assert svc.to_sandbox(claim, paused).status == SandboxStatus.STOPPED
    assert svc.to_sandbox(claim, None).status == SandboxStatus.CREATED


class FakeObjects:
    def __init__(self, items: list[dict] | None = None) -> None:
        self.items = items or []
        self.saved: list[dict] = []

    def list(self, _selector: str = ""):
        return list(self.items)

    def get(self, name: str):
        for item in self.items:
            if item["metadata"]["name"] == name:
                return item
        from kubernetes.client import ApiException

        raise ApiException(status=404, reason="Not Found")

    def create(self, body: dict):
        self.saved.append(body)
        return body

    def patch(self, name: str, body: dict):
        self.saved.append({"name": name, **body})
        return body


def test_pool_repository_maps_warm_pool_and_hides_implicit() -> None:
    repo = SandboxPoolRepository(SimpleNamespace(namespace="default", available_runtime_classes=set()), settings())
    warmpool = {
        "metadata": {
            "name": "ubuntu",
            "creationTimestamp": "2026-01-01T00:00:00Z",
            "annotations": {
                "litterbox.io/min-ready": "1",
                "litterbox.io/max-creating": "2",
            },
        },
        "spec": {"replicas": 3, "sandboxTemplateRef": {"name": "ubuntu"}},
        "status": {"readyReplicas": 2},
    }
    implicit = {
        "metadata": {"name": "other", "annotations": {"litterbox.io/implicit": "true"}},
        "spec": {"replicas": 0},
    }
    repo.warmpools = FakeObjects([warmpool, implicit])
    repo.claims = FakeObjects(
        [
            {"metadata": {"name": "a"}, "spec": {}},
            {"metadata": {"name": "b", "deletionTimestamp": "2026-01-01T00:00:00Z"}, "spec": {}},
        ]
    )

    pool = repo.get("ubuntu")
    assert pool is not None
    assert pool.target_ready == 3
    assert pool.min_ready == 1
    assert pool.max_creating == 2
    assert repo.get("other") is None
    assert [p.template_id for p in repo.list()] == ["ubuntu"]
    assert repo.get_status("ubuntu") == {
        "replicas": 3,
        "ready": 2,
        "creating": 1,
        "allocated": 1,
        "failed": 0,
        "terminating": 1,
    }
