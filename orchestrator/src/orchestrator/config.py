from __future__ import annotations

from functools import lru_cache
import json
import os
from pathlib import Path
import tomllib

from pydantic import BaseModel, Field


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8080


class KubernetesConfig(BaseModel):
    kubeconfig: str | None = None
    namespace: str = "default"
    runtime_class: str | None = None
    storage_class: str | None = None
    image_pull_secret: str | None = None


class SandboxConfig(BaseModel):
    max_sandboxes: int = 1000
    base_domain: str = "runlet.cn"


class TTLConfig(BaseModel):
    default_ttl_seconds: int = 1800
    min_ttl_seconds: int = 60
    max_ttl_seconds: int = 86400
    queue_key: str = "orchestrator:ttl"
    worker_poll_interval_seconds: float = 1.0


class WebhookConfig(BaseModel):
    max_attempts: int = 5
    interval_ms: int = 200
    timeout_ms: int = 1000


class CeleryConfig(BaseModel):
    broker_url: str = "redis://127.0.0.1:6379/2"
    result_backend: str = "redis://127.0.0.1:6379/2"
    webhook_queue: str = "webhook_delivery"


class Settings(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    kubernetes: KubernetesConfig = Field(default_factory=KubernetesConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    ttl: TTLConfig = Field(default_factory=TTLConfig)
    webhook: WebhookConfig = Field(default_factory=WebhookConfig)
    celery: CeleryConfig = Field(default_factory=CeleryConfig)


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
