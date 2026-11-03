from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class E2BCreateSandboxRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    template_id: str = Field(alias="templateID", min_length=1)
    timeout: int = Field(default=300, ge=0)
    metadata: dict[str, str] = Field(default_factory=dict)
    env_vars: dict[str, str] = Field(default_factory=dict, alias="envVars")
    secure: bool = True
    allow_internet_access: bool | None = None


class E2BConnectSandboxRequest(BaseModel):
    timeout: int = Field(default=300, ge=0)


class E2BPauseSandboxRequest(BaseModel):
    memory: bool = True


class E2BTimeoutRequest(BaseModel):
    timeout: int = Field(ge=0)


class E2BSandboxCreateResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    template_id: str = Field(alias="templateID")
    sandbox_id: str = Field(alias="sandboxID")
    client_id: str = Field(alias="clientID")
    domain: str
    envd_version: str = Field(alias="envdVersion")
    envd_access_token: str | None = Field(default=None, alias="envdAccessToken")
    traffic_access_token: str | None = Field(default=None, alias="trafficAccessToken")


class E2BSandboxDetail(BaseModel):
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    sandbox_id: str = Field(alias="sandboxID")
    template_id: str = Field(alias="templateID")
    domain: str
    state: str
    metadata: dict[str, str] = Field(default_factory=dict)
    envd_version: str = Field(alias="envdVersion")
    envd_access_token: str | None = Field(default=None, alias="envdAccessToken")
    traffic_access_token: str | None = Field(default=None, alias="trafficAccessToken")
    started_at: Any | None = Field(default=None, alias="startedAt")
    end_at: Any | None = Field(default=None, alias="endAt")
