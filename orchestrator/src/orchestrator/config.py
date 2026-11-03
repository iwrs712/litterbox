from __future__ import annotations

from functools import lru_cache
import json
import os
from pathlib import Path
import tomllib

from pydantic import BaseModel, Field, field_validator


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8080


class KubernetesConfig(BaseModel):
    kubeconfig: str | None = None
    namespace: str = "default"
    runtime_class: str | None = "kata-clh"
    # Kept as a fallback for installations that have not moved storage settings
    # into the workspace section yet.
    storage_class: str | None = None
    image_pull_secret: str | None = None


class SandboxConfig(BaseModel):
    max_sandboxes: int = 1000
    base_domain: str = "example.com"
    crd_group: str = "litterbox.io"
    crd_version: str = "v1alpha1"
    crd_plural: str = "sandboxes"


class WorkspaceConfig(BaseModel):
    enabled: bool = True
    mount_path: str = "/workspace"
    default_size: str = "1Gi"
    storage_class: str | None = None

    @field_validator("mount_path")
    @classmethod
    def mount_path_must_be_absolute(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("workspace.mount_path must be an absolute path")
        return value.rstrip("/") or "/"


class EnvdConfig(BaseModel):
    enabled: bool = False
    version: str = "0.1.0"
    host_binary_path: str = "/opt/litterbox/bin/envd"
    container_binary_path: str = "/opt/litterbox/bin/envd"
    port: int = Field(default=49983, ge=1, le=65535)
    connect_timeout_seconds: float = Field(default=3.0, gt=0)
    pod_ip_cache_ttl_seconds: float = Field(default=5.0, ge=0)

    @field_validator("host_binary_path", "container_binary_path")
    @classmethod
    def binary_paths_must_be_absolute(cls, value: str) -> str:
        if not Path(value).is_absolute():
            raise ValueError("envd binary paths must be absolute")
        return value

    @field_validator("version")
    @classmethod
    def version_must_not_be_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("envd.version must not be empty")
        return value


class E2BConfig(BaseModel):
    enabled: bool = False
    api_key: str = ""
    domain: str = "sandbox.example.com"
    envd_version: str = "0.1.0"


class TTLConfig(BaseModel):
    default_ttl_seconds: int = 1800


class WebhookConfig(BaseModel):
    max_attempts: int = 5
    interval_ms: int = 200
    timeout_ms: int = 1000


class CeleryConfig(BaseModel):
    broker_url: str = "redis://127.0.0.1:6379/2"
    result_backend: str = "redis://127.0.0.1:6379/2"
    webhook_queue: str = "webhook_delivery"


class AuthConfig(BaseModel):
    bearer_token: str = ""


class Settings(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    kubernetes: KubernetesConfig = Field(default_factory=KubernetesConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    workspace: WorkspaceConfig = Field(default_factory=WorkspaceConfig)
    envd: EnvdConfig = Field(default_factory=EnvdConfig)
    e2b: E2BConfig = Field(default_factory=E2BConfig)
    ttl: TTLConfig = Field(default_factory=TTLConfig)
    webhook: WebhookConfig = Field(default_factory=WebhookConfig)
    celery: CeleryConfig = Field(default_factory=CeleryConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)


ENV_PREFIX = "ORCHESTRATOR__"


def _parse_env_override(raw_value: str):
    if raw_value == "":
        return ""
    try:
        return json.loads(raw_value)
    except json.JSONDecodeError:
        return raw_value


def _set_nested_override(target: dict, path: list[str], value) -> None:
    current = target
    for key in path[:-1]:
        current = current.setdefault(key, {})
    current[path[-1]] = value


def _apply_env_overrides(raw: dict) -> dict:
    merged = dict(raw)
    for env_name, env_value in os.environ.items():
        if not env_name.startswith(ENV_PREFIX):
            continue
        path = [part.lower() for part in env_name[len(ENV_PREFIX) :].split("__") if part]
        if not path:
            continue
        _set_nested_override(merged, path, _parse_env_override(env_value))
    return merged


def _load_settings() -> Settings:
    root = Path(__file__).resolve().parents[2]
    config_path = root / "config.toml"
    with config_path.open("rb") as fh:
        raw = tomllib.load(fh)

    settings = Settings.model_validate(_apply_env_overrides(raw))
    if settings.kubernetes.kubeconfig:
        kubeconfig = Path(settings.kubernetes.kubeconfig)
        if not kubeconfig.is_absolute():
            settings.kubernetes.kubeconfig = str((root / kubeconfig).resolve())
    return settings


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return _load_settings()
