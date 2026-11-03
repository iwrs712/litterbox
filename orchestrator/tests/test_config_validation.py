from __future__ import annotations

import pytest

from orchestrator.config import EnvdConfig, Settings


def test_envd_config_defaults_to_disabled() -> None:
    envd = Settings().envd

    assert envd == EnvdConfig(
        enabled=False,
        version="0.1.0",
        host_binary_path="/opt/litterbox/bin/envd",
        container_binary_path="/opt/litterbox/bin/envd",
        port=49983,
        connect_timeout_seconds=3.0,
        pod_ip_cache_ttl_seconds=5.0,
    )


@pytest.mark.parametrize("field", ["host_binary_path", "container_binary_path"])
def test_envd_binary_paths_must_be_absolute(field: str) -> None:
    with pytest.raises(ValueError, match="envd binary paths must be absolute"):
        EnvdConfig.model_validate({field: "relative/envd"})


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


def test_workspace_defaults() -> None:
    settings = Settings()

    assert settings.workspace.default_size == "1Gi"
    assert settings.workspace.mount_path == "/workspace"
    assert settings.kubernetes.runtime_class == "kata-clh"


def test_workspace_mount_path_must_be_absolute() -> None:
    with pytest.raises(ValueError, match="workspace.mount_path must be an absolute path"):
        Settings.model_validate({"workspace": {"mount_path": "workspace"}})
