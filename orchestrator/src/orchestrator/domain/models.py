from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from math import ceil
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def utcnow() -> datetime:
    return datetime.now(tz=UTC)


class SandboxStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    STOPPED = "stopped"
    EXITED = "exited"
    UNKNOWN = "unknown"
    POOLED = "pooled"
    CREATING = "creating"


class PoolState(StrEnum):
    NONE = "none"
    CREATING = "creating"
    AVAILABLE = "available"
    ALLOCATED = "allocated"
    FAILED = "failed"


class ProtocolType(StrEnum):
    HTTP = "http"
    TCP = "tcp"


class ExposeStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


class WebhookEvent(StrEnum):
    SANDBOX_STARTED = "sandbox_started"
    SANDBOX_READY = "sandbox_ready"
    SANDBOX_DELETED = "sandbox_deleted"


class HostPathMount(BaseModel):
    host_path: str
    container_path: str
    read_only: bool = False


class LifecycleExecAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: list[str] = Field(min_length=1)

    @field_validator("command")
    @classmethod
    def validate_command(cls, value: list[str]) -> list[str]:
        if any(not item for item in value):
            raise ValueError("lifecycle exec command entries must be non-empty strings")
        return value


class LifecycleAction(BaseModel):
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True, extra="forbid")

    exec: LifecycleExecAction


class PreStopLifecycleAction(LifecycleAction):
    termination_grace_period_seconds: int | None = Field(
        default=None,
        alias="terminationGracePeriodSeconds",
        ge=1,
        le=300,
    )


class SandboxLifecycle(BaseModel):
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True, extra="forbid")

    post_start: LifecycleAction | None = Field(default=None, alias="postStart")
    pre_stop: PreStopLifecycleAction | None = Field(default=None, alias="preStop")

    @model_validator(mode="after")
    def require_action(self) -> "SandboxLifecycle":
        if self.post_start is None and self.pre_stop is None:
            raise ValueError("lifecycle must define at least one action")
        return self


class Template(BaseModel):
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    id: str
    name: str
    description: str = ""
    image: str
    command: str = ""
    env: list[str] = Field(default_factory=list)
    cpu_millicores: int
    cpu_request: int | None = None
    memory_mb: int
    memory_request: int | None = None
    host_path_mounts: list[HostPathMount] = Field(default_factory=list)
    ttl_seconds: int | None = None
    lifecycle: SandboxLifecycle | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    @field_validator("command", mode="before")
    @classmethod
    def normalize_command(cls, value):
        if isinstance(value, list):
            return " ".join(str(item) for item in value)
        return value or ""


class CreateTemplateRequest(BaseModel):
    id: str = ""
    name: str
    description: str = ""
    image: str
    command: str = ""
    env: list[str] = Field(default_factory=list)
    cpu_millicores: int = Field(ge=100, le=128000)
    cpu_request: int | None = Field(default=None, ge=100, le=128000)
    memory_mb: int = Field(ge=128, le=131072)
    memory_request: int | None = Field(default=None, ge=128, le=131072)
    host_path_mounts: list[HostPathMount] = Field(default_factory=list)
    ttl_seconds: int | None = Field(default=None, ge=60, le=86400)
    lifecycle: SandboxLifecycle | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class UpdateTemplateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    image: str | None = None
    command: str | None = None
    env: list[str] | None = None
    cpu_millicores: int | None = Field(default=None, ge=100, le=128000)
    cpu_request: int | None = Field(default=None, ge=100, le=128000)
    memory_mb: int | None = Field(default=None, ge=128, le=131072)
    memory_request: int | None = Field(default=None, ge=128, le=131072)
    host_path_mounts: list[HostPathMount] | None = None
    ttl_seconds: int | None = Field(default=None, ge=60, le=86400)
    lifecycle: SandboxLifecycle | None = None
    metadata: dict[str, str] | None = None


class TemplateListParams(BaseModel):
    page: int = 1
    page_size: int = 10
    name: str = ""
    user_id: str = ""


class TemplateListResponse(BaseModel):
    templates: list[Template]
    total: int
    page: int
    page_size: int
    total_pages: int

    @classmethod
    def from_items(cls, items: list[Template], page: int, page_size: int) -> "TemplateListResponse":
        total = len(items)
        start = max(page - 1, 0) * page_size
        end = start + page_size
        paged = items[start:end]
        total_pages = ceil(total / page_size) if page_size else 0
        return cls(
            templates=paged,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )


class Pool(BaseModel):
    template_id: str
    enabled: bool
    min_ready: int = 0
    target_ready: int = 0
    max_creating: int = 5
    created_at: datetime
    updated_at: datetime


class PoolStatus(BaseModel):
    template_id: str
    enabled: bool
    min_ready: int
    target_ready: int
    max_creating: int
    ready: int
    creating: int
    allocated: int
    failed: int
    terminating: int


class PoolListResponse(BaseModel):
    pools: list[PoolStatus]
    total: int


class CreatePoolRequest(BaseModel):
    min_ready: int = Field(ge=1, le=50)
    target_ready: int | None = Field(default=None, ge=1, le=100)
    max_creating: int = Field(default=5, ge=1, le=20)


class UpdatePoolRequest(BaseModel):
    min_ready: int | None = Field(default=None, ge=0, le=50)
    target_ready: int | None = Field(default=None, ge=1, le=100)
    max_creating: int | None = Field(default=None, ge=1, le=20)


class AllocateSandboxRequest(BaseModel):
    name: str = ""
    template_id: str
    metadata: dict[str, str] = Field(default_factory=dict)


class UpdateSandboxRequest(BaseModel):
    name: str = ""
    metadata: dict[str, str] | None = None


class Sandbox(BaseModel):
    id: str
    name: str = ""
    template_id: str
    status: SandboxStatus
    terminating: bool = False
    pool_state: str = PoolState.NONE
    metadata: dict[str, str] = Field(default_factory=dict)
    allocated_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    ttl_seconds: int = 0
    expires_at: datetime | None = None


class SandboxResponse(BaseModel):
    id: str
    name: str = ""
    template_id: str = ""
    image: str = ""
    cpu_millicores: int = 0
    memory_mb: int = 0
    status: SandboxStatus
    terminating: bool = False
    pool_state: str
    metadata: dict[str, str] = Field(default_factory=dict)
    allocated_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    ttl_seconds: int = 0
    expires_at: datetime | None = None
    time_remaining_seconds: int = 0

    @classmethod
    def from_sandbox(cls, sandbox: Sandbox, template: Template | None) -> "SandboxResponse":
        time_remaining = 0
        if sandbox.expires_at is not None:
            remaining = int((sandbox.expires_at - utcnow()).total_seconds())
            time_remaining = max(remaining, 0)
        return cls(
            id=sandbox.id,
            name=sandbox.name,
            template_id=sandbox.template_id,
            image=template.image if template else "",
            cpu_millicores=template.cpu_millicores if template else 0,
            memory_mb=template.memory_mb if template else 0,
            status=sandbox.status,
            terminating=sandbox.terminating,
            pool_state=sandbox.pool_state,
            metadata=sandbox.metadata,
            allocated_at=sandbox.allocated_at,
            created_at=sandbox.created_at,
            updated_at=sandbox.updated_at,
            ttl_seconds=sandbox.ttl_seconds,
            expires_at=sandbox.expires_at,
            time_remaining_seconds=time_remaining,
        )


class SandboxListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    sandboxes: list[SandboxResponse]


class QueryOptions(BaseModel):
    page: int = 1
    page_size: int = 20
    status: SandboxStatus | None = None
    pool_state: str = ""
    template_id: str = ""
    metadata: dict[str, str] = Field(default_factory=dict)
    name: str = ""


class CreateServiceExposeRequest(BaseModel):
    sandbox_id: str = ""
    name: str = ""
    protocol: ProtocolType
    internal_port: int = Field(ge=1, le=65535)
    domain: str = ""
    path: str = ""


class ServiceExpose(BaseModel):
    id: str
    sandbox_id: str
    name: str = ""
    protocol: ProtocolType
    internal_port: int
    external_url: str = ""
    domain: str = ""
    path: str = ""
    external_ip: str = ""
    external_port: int = 0
    service_name: str = ""
    ingress_name: str = ""
    status: ExposeStatus
    message: str = ""
    created_at: datetime
    updated_at: datetime


class ServiceExposeListResponse(BaseModel):
    exposes: list[ServiceExpose]
    total: int


class WebhookRetryConfig(BaseModel):
    max_attempts: int = 5
    interval_ms: int = 200
    timeout_ms: int = 1000


class Webhook(BaseModel):
    id: str
    name: str
    user_id: str
    url: str
    token: str = ""
    template_ids: list[str] = Field(default_factory=list)
    events: list[WebhookEvent] = Field(default_factory=list)
    retry: WebhookRetryConfig = Field(default_factory=WebhookRetryConfig)
    enabled: bool = True
    created_at: datetime
    updated_at: datetime


class CreateWebhookRequest(BaseModel):
    id: str = ""
    name: str
    user_id: str
    url: str
    token: str = ""
    template_ids: list[str] = Field(default_factory=list)
    events: list[WebhookEvent] = Field(default_factory=list)
    retry: WebhookRetryConfig = Field(default_factory=WebhookRetryConfig)
    enabled: bool | None = None


class UpdateWebhookRequest(BaseModel):
    name: str | None = None
    url: str | None = None
    token: str | None = None
    template_ids: list[str] | None = None
    events: list[WebhookEvent] | None = None
    retry: WebhookRetryConfig | None = None
    enabled: bool | None = None


class WebhookListParams(BaseModel):
    user_id: str = ""


class WebhookK8sInfo(BaseModel):
    namespace: str
    pod_name: str = ""
    pod_ip: str = ""
    node_name: str = ""
    container_name: str = ""


class WebhookPayload(BaseModel):
    event_id: str
    event_type: WebhookEvent
    occurred_at: datetime
    deletion_reason: str = ""
    sandbox: SandboxResponse
    template: Template | None = None
    kubernetes: WebhookK8sInfo | None = None


class ApiResponse(BaseModel):
    success: bool
    message: str | None = None
    data: Any | None = None
    error: str | None = None


class FileKind(StrEnum):
    FILE = "file"
    DIRECTORY = "directory"


class FileView(StrEnum):
    AUTO = "auto"
    CONTENT = "content"
    LIST = "list"
    TREE = "tree"


class ExecCommandRequest(BaseModel):
    command: list[str]
    workdir: str | None = None
    timeout: int = Field(default=30, ge=1, le=3600)

    @field_validator("command")
    @classmethod
    def validate_command(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("command must not be empty")
        return value


class ExecCommandResult(BaseModel):
    exit_code: int
    stdout: str
    stderr: str
    execution_time_ms: int


class FileNode(BaseModel):
    name: str
    path: str
    is_dir: bool
    size: int | None = None
    children: list["FileNode"] = Field(default_factory=list)


class FileListResponse(BaseModel):
    path: str
    is_dir: bool
    entries: list[FileNode] = Field(default_factory=list)


class FileWriteResult(BaseModel):
    path: str
    kind: FileKind
    size: int


class FileDeleteResult(BaseModel):
    path: str
    deleted: bool = True


FileNode.model_rebuild()
