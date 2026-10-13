from __future__ import annotations

import re
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from kubernetes.client import ApiException

from orchestrator.container import Container
from orchestrator.deps import get_container
from orchestrator.domain.models import SandboxStatus
from orchestrator.infra.kubernetes import (
    SandboxNotRunningError,
    SandboxPodAddressUnavailableError,
)
from orchestrator.responses import error
from orchestrator.services.envd_proxy import EnvdUpstreamUnavailableError

router = APIRouter(tags=["envd"])
_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
_SANDBOX_HOST_RE = re.compile(r"^(?P<port>[0-9]+)-(?P<sandbox_id>[a-z0-9][a-z0-9-]*)\.(?P<domain>.+)$")


def parse_sandbox_envd_host(host: str | None, domain: str, envd_port: int) -> str | None:
    """Return a sandbox ID for an E2B-style envd hostname."""
    if not host or not domain:
        return None
    hostname = host.split(":", 1)[0].lower().rstrip(".")
    match = _SANDBOX_HOST_RE.fullmatch(hostname)
    if match is None or match.group("domain") != domain.lower().rstrip("."):
        return None
    if int(match.group("port")) != envd_port:
        return None
    return match.group("sandbox_id")


async def _proxy_envd(
    sandbox_id: str,
    envd_path: str,
    request: Request,
    container: Container,
):
    try:
        sandbox = container.sandbox_service.get_sandbox(sandbox_id)
    except (KeyError, FileNotFoundError):
        return error("Sandbox not found", 404)
    except ApiException as exc:
        if exc.status != 404:
            raise
        return error("Sandbox not found", 404)

    if sandbox.status == SandboxStatus.STOPPED:
        return error(f"sandbox {sandbox_id} is not running", 409)

    try:
        return await container.envd_proxy_service.proxy(sandbox_id, envd_path, request)
    except SandboxNotRunningError as exc:
        return error(str(exc), 409)
    except SandboxPodAddressUnavailableError as exc:
        return error(str(exc), 503)
    except EnvdUpstreamUnavailableError as exc:
        return error(str(exc), 502)


@router.api_route(
    "/api/v1/sandboxes/{sandbox_id}/envd",
    methods=_METHODS,
)
async def proxy_envd_root(
    sandbox_id: str,
    request: Request,
    container: Annotated[Container, Depends(get_container)],
):
    return await _proxy_envd(sandbox_id, "", request, container)


@router.api_route(
    "/api/v1/sandboxes/{sandbox_id}/envd/{envd_path:path}",
    methods=_METHODS,
)
async def proxy_envd_path(
    sandbox_id: str,
    envd_path: str,
    request: Request,
    container: Annotated[Container, Depends(get_container)],
):
    return await _proxy_envd(sandbox_id, envd_path, request, container)
