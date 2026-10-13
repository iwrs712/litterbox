from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, Response

from orchestrator.container import Container
from orchestrator.deps import get_container
from orchestrator.domain.e2b_models import (
    E2BConnectSandboxRequest,
    E2BCreateSandboxRequest,
    E2BPauseSandboxRequest,
    E2BTimeoutRequest,
)
from orchestrator.services.e2b import E2BUnsupportedOperationError
from orchestrator.services.sandboxes import SandboxResumeLockedError

router = APIRouter(prefix="/e2b", tags=["e2b"])


def _enabled(container: Container) -> bool:
    return container.settings.e2b.enabled


def _e2b_error(message: str, status_code: int, code: str | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"code": code or str(status_code), "message": message},
    )


@router.post("/sandboxes", status_code=201)
def create_sandbox(
    request: E2BCreateSandboxRequest,
    container: Annotated[Container, Depends(get_container)],
):
    if not _enabled(container):
        return _e2b_error("E2B control plane is disabled", 404, "not_found")
    try:
        return JSONResponse(
            status_code=201,
            content=container.e2b_service.create(request).model_dump(mode="json", by_alias=True),
        )
    except E2BUnsupportedOperationError as exc:
        return _e2b_error(str(exc), 400, "invalid_argument")
    except ValueError as exc:
        return _e2b_error(str(exc), 400, "invalid_argument")
    except Exception as exc:  # noqa: BLE001
        return _e2b_error(str(exc), 500, "internal")


@router.get("/sandboxes/{sandbox_id}")
def get_sandbox(sandbox_id: str, container: Annotated[Container, Depends(get_container)]):
    if not _enabled(container):
        return _e2b_error("E2B control plane is disabled", 404, "not_found")
    try:
        return JSONResponse(content=container.e2b_service.get(sandbox_id).model_dump(mode="json", by_alias=True))
    except Exception as exc:  # noqa: BLE001
        return _e2b_error(str(exc), 404, "not_found")


@router.post("/sandboxes/{sandbox_id}/connect")
def connect_sandbox(
    sandbox_id: str,
    request: E2BConnectSandboxRequest,
    container: Annotated[Container, Depends(get_container)],
):
    if not _enabled(container):
        return _e2b_error("E2B control plane is disabled", 404, "not_found")
    try:
        data = container.e2b_service.connect(sandbox_id, request)
        return JSONResponse(content=data.model_dump(mode="json", by_alias=True))
    except SandboxResumeLockedError as exc:
        return _e2b_error(str(exc), 409, "conflict")
    except Exception as exc:  # noqa: BLE001
        return _e2b_error(str(exc), 404, "not_found")


@router.post("/sandboxes/{sandbox_id}/pause")
def pause_sandbox(
    sandbox_id: str,
    request: E2BPauseSandboxRequest,
    container: Annotated[Container, Depends(get_container)],
):
    if not _enabled(container):
        return _e2b_error("E2B control plane is disabled", 404, "not_found")
    try:
        container.e2b_service.pause(sandbox_id, keep_memory=request.memory)
        return Response(status_code=200)
    except E2BUnsupportedOperationError as exc:
        return _e2b_error(str(exc), 409, "conflict")
    except Exception as exc:  # noqa: BLE001
        return _e2b_error(str(exc), 404, "not_found")


@router.post("/sandboxes/{sandbox_id}/timeout", status_code=204)
def set_timeout(
    sandbox_id: str,
    request: E2BTimeoutRequest,
    container: Annotated[Container, Depends(get_container)],
):
    if not _enabled(container):
        return _e2b_error("E2B control plane is disabled", 404, "not_found")
    try:
        container.e2b_service.set_timeout(sandbox_id, request.timeout)
        return Response(status_code=204)
    except Exception as exc:  # noqa: BLE001
        return _e2b_error(str(exc), 404, "not_found")


@router.delete("/sandboxes/{sandbox_id}", status_code=204)
def kill_sandbox(sandbox_id: str, container: Annotated[Container, Depends(get_container)]):
    if not _enabled(container):
        return _e2b_error("E2B control plane is disabled", 404, "not_found")
    try:
        container.e2b_service.kill(sandbox_id)
        return Response(status_code=204)
    except Exception as exc:  # noqa: BLE001
        return _e2b_error(str(exc), 404, "not_found")
