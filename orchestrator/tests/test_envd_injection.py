from __future__ import annotations

from types import SimpleNamespace

import pytest

from orchestrator.config import EnvdConfig, Settings
from orchestrator.domain.models import Template, utcnow
from orchestrator.services.sandboxes import SandboxService


def build_template(lifecycle: dict | None = None) -> Template:
    now = utcnow()
    return Template.model_validate(
        {
            "id": "tpl-envd",
            "name": "envd template",
            "image": "ubuntu:24.04",
            "cpu_millicores": 1000,
            "memory_mb": 512,
            "lifecycle": lifecycle,
            "created_at": now,
            "updated_at": now,
        }
    )


def build_service(envd: EnvdConfig) -> SandboxService:
    service = object.__new__(SandboxService)
    service.gateway = SimpleNamespace(
        namespace="default",
        available_runtime_classes=set(),
        secret_exists=lambda _name: False,
    )
    service.settings = Settings(envd=envd)
    return service


def build_deployment(service: SandboxService, template: Template):
    return service._build_deployment(
        sandbox_id="sbx-envd",
        template=template,
        metadata={},
        name="",
        env=None,
        pool_state="none",
        ttl_seconds=None,
    )


def test_envd_config_defaults_to_disabled() -> None:
    envd = Settings().envd

    assert envd == EnvdConfig(
        enabled=False,
        version="0.1.0",
        host_binary_path="/opt/litterbox/bin/sandbox-agent",
        container_binary_path="/opt/litterbox/envd/sandbox-agent",
        port=49983,
        connect_timeout_seconds=3.0,
        pod_ip_cache_ttl_seconds=5.0,
    )


@pytest.mark.parametrize("field", ["host_binary_path", "container_binary_path"])
def test_envd_binary_paths_must_be_absolute(field: str) -> None:
    with pytest.raises(ValueError, match="envd binary paths must be absolute"):
        EnvdConfig.model_validate({field: "relative/sandbox-agent"})


def test_envd_version_must_not_be_empty() -> None:
    with pytest.raises(ValueError, match="envd.version must not be empty"):
        EnvdConfig.model_validate({"version": "  "})


@pytest.mark.parametrize(
    ("values", "error"),
    [
        ({"port": 0}, "greater than or equal to 1"),
        ({"port": 65536}, "less than or equal to 65535"),
        ({"connect_timeout_seconds": 0}, "greater than 0"),
        ({"pod_ip_cache_ttl_seconds": -1}, "greater than or equal to 0"),
    ],
)
def test_envd_numeric_settings_are_validated(values: dict, error: str) -> None:
    with pytest.raises(ValueError, match=error):
        EnvdConfig.model_validate(values)


def test_build_deployment_injects_envd() -> None:
    service = build_service(EnvdConfig(enabled=True))
    deployment = build_deployment(service, build_template())
    pod_spec = deployment.spec.template.spec
    container = pod_spec.containers[0]
    volume = next(item for item in pod_spec.volumes if item.name == "envd")
    mount = next(item for item in container.volume_mounts if item.name == "envd")

    assert volume.host_path.path == "/opt/litterbox/bin/sandbox-agent"
    assert volume.host_path.type == "File"
    assert mount.mount_path == "/opt/litterbox/envd/sandbox-agent"
    assert mount.read_only is True
    assert container.lifecycle.post_start._exec.command == [
        "/opt/litterbox/envd/sandbox-agent",
        "daemon",
        "--host",
        "0.0.0.0",
        "--port",
        "49983",
        "--filesystem-root",
        "/",
    ]
    assert [(item.name, item.container_port) for item in container.ports] == [("envd", 49983)]
    assert pod_spec.node_selector == {"litterbox.io/envd-version": "0.1.0"}
    assert deployment.metadata.annotations["litterbox.io/envd-version"] == "0.1.0"
    assert deployment.spec.template.metadata.annotations["litterbox.io/envd-version"] == "0.1.0"


def test_envd_injection_preserves_template_pre_stop_and_grace_period() -> None:
    service = build_service(EnvdConfig(enabled=True))
    template = build_template(
        {
            "preStop": {
                "exec": {"command": ["/bin/sh", "-lc", "echo stopping"]},
                "terminationGracePeriodSeconds": 30,
            }
        }
    )

    deployment = build_deployment(service, template)
    pod_spec = deployment.spec.template.spec
    container = pod_spec.containers[0]

    assert pod_spec.termination_grace_period_seconds == 30
    assert container.lifecycle.pre_stop._exec.command == ["/bin/sh", "-lc", "echo stopping"]


def test_envd_injection_rejects_template_post_start() -> None:
    service = build_service(EnvdConfig(enabled=True))
    template = build_template(
        {"postStart": {"exec": {"command": ["/bin/sh", "-lc", "echo started"]}}}
    )

    with pytest.raises(ValueError, match="^template postStart conflicts with envd injection$"):
        build_deployment(service, template)


def test_disabled_envd_injection_leaves_pod_spec_unchanged() -> None:
    service = build_service(EnvdConfig(enabled=False))
    deployment = build_deployment(service, build_template())
    pod_spec = deployment.spec.template.spec
    container = pod_spec.containers[0]

    assert all(volume.name != "envd" for volume in pod_spec.volumes or [])
    assert all(mount.name != "envd" for mount in container.volume_mounts or [])
    assert container.ports is None
    assert container.lifecycle is None
    assert pod_spec.node_selector is None
