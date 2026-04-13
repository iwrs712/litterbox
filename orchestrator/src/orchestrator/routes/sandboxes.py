from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response

from orchestrator.container import Container
from orchestrator.deps import get_container
from orchestrator.domain.models import (
    AllocateSandboxRequest,
    ExecCommandRequest,
    FileKind,
    FileView,
    QueryOptions,
    UpdateSandboxRequest,
)
from orchestrator.responses import error, ok, parse_timeout
from orchestrator.utils import validate_metadata_key

router = APIRouter(prefix="/api/v1/sandboxes", tags=["sandboxes"])


def validate_metadata(metadata: dict[str, str] | None) -> None:
    if not metadata:
        return
    for key in metadata:
        validate_metadata_key(key)


@router.post("")
def create_sandbox(
    request: AllocateSandboxRequest,
    container: Annotated[Container, Depends(get_container)],
) -> JSONResponse:
    try:
        validate_metadata(request.metadata)
        sandbox = container.pool_service.allocate_sandbox(request)
        return ok(data=sandbox, message="Sandbox allocated successfully", status_code=201)
    except ValueError as exc:
        return error(str(exc), 400)
    except Exception as exc:  # noqa: BLE001
        return error(str(exc), 500)


@router.get("")
def list_sandboxes(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1),
    status: str = "",
    name: str = "",
    template_id: str = "",
    pool_state: str = "",
    container: Annotated[Container, Depends(get_container)] = None,
) -> JSONResponse:
    try:
        opts = QueryOptions(
            page=page,
            page_size=page_size,
            status=status or None,
            name=name,
            template_id=template_id,
            pool_state=pool_state,
        )
        return ok(data=container.sandbox_service.list_sandboxes(opts))
    except Exception as exc:  # noqa: BLE001
        return error(str(exc), 500)


@router.post("/query")
def query_sandboxes(
    request: QueryOptions,
    container: Annotated[Container, Depends(get_container)],
) -> JSONResponse:
    try:
        return ok(data=container.sandbox_service.list_sandboxes(request))
    except Exception as exc:  # noqa: BLE001
        return error(str(exc), 500)


@router.get("/{sandbox_id}")
def get_sandbox(
    sandbox_id: str,
    container: Annotated[Container, Depends(get_container)],
) -> JSONResponse:
    try:
        return ok(data=container.sandbox_service.get_sandbox(sandbox_id))
    except Exception:
        return error("Sandbox not found", 404)


@router.patch("/{sandbox_id}")
def update_sandbox(
    sandbox_id: str,
    request: UpdateSandboxRequest,
    container: Annotated[Container, Depends(get_container)],
) -> JSONResponse:
    try:
        validate_metadata(request.metadata)
        sandbox = container.sandbox_service.update_sandbox(sandbox_id, request)
        return ok(data=sandbox, message="Sandbox updated successfully")
    except ValueError as exc:
        return error(str(exc), 400)
    except Exception as exc:  # noqa: BLE001
        return error(str(exc), 500)


@router.delete("/{sandbox_id}")
def delete_sandbox(
    sandbox_id: str,
    container: Annotated[Container, Depends(get_container)],
) -> JSONResponse:
    try:
        container.pool_service.release_sandbox(sandbox_id)
        return ok(message="Sandbox deleted successfully")
    except Exception as exc:  # noqa: BLE001
        return error(str(exc), 500)


@router.post("/{sandbox_id}/start")
def start_sandbox(
    sandbox_id: str,
    container: Annotated[Container, Depends(get_container)],
) -> JSONResponse:
    try:
        container.sandbox_service.start_sandbox(sandbox_id)
        return ok(message="Sandbox started successfully")
    except Exception as exc:  # noqa: BLE001
        return error(str(exc), 500)


@router.post("/{sandbox_id}/stop")
def stop_sandbox(
    sandbox_id: str,
    timeout: str | None = None,
    container: Annotated[Container, Depends(get_container)] = None,
) -> JSONResponse:
    try:
        container.sandbox_service.stop_sandbox(sandbox_id, grace_period_seconds=parse_timeout(timeout))
        return ok(message="Sandbox stopped successfully")
    except Exception as exc:  # noqa: BLE001
        return error(str(exc), 500)


@router.post("/{sandbox_id}/restart")
def restart_sandbox(
    sandbox_id: str,
    timeout: str | None = None,
    container: Annotated[Container, Depends(get_container)] = None,
) -> JSONResponse:
    try:
        container.sandbox_service.restart_sandbox(sandbox_id, parse_timeout(timeout))
        return ok(message="Sandbox restarted successfully")
    except Exception as exc:  # noqa: BLE001
        return error(str(exc), 500)


@router.post("/{sandbox_id}/exec")
def exec_command(
    sandbox_id: str,
    request: ExecCommandRequest,
    container: Annotated[Container, Depends(get_container)],
) -> JSONResponse:
    try:
        result = container.workspace_service.exec_command(sandbox_id, request)
        return ok(data=result)
    except ValueError as exc:
        return error(str(exc), 400)
    except Exception as exc:  # noqa: BLE001
        return error(str(exc), 500)


@router.get("/{sandbox_id}/files")
def get_files(
    sandbox_id: str,
    path: str = Query(default="/workspace"),
    view: FileView = Query(default=FileView.AUTO),
    container: Annotated[Container, Depends(get_container)] = None,
):
    try:
        media_type, data = container.workspace_service.get_path(sandbox_id, path, view)
        if isinstance(data, bytes):
            return Response(content=data, media_type=media_type, headers={"X-Litterbox-Path": path})
        return ok(data=data)
    except FileNotFoundError:
        return error("Path not found", 404)
    except ValueError as exc:
        return error(str(exc), 400)
    except Exception as exc:  # noqa: BLE001
        return error(str(exc), 500)


@router.put("/{sandbox_id}/files")
async def put_files(
    sandbox_id: str,
    request: Request,
    path: str = Query(...),
    kind: FileKind = Query(default=FileKind.FILE),
    container: Annotated[Container, Depends(get_container)] = None,
):
    try:
        payload = await request.body()
        result = container.workspace_service.put_path(sandbox_id, path, kind, payload)
        return ok(data=result)
    except ValueError as exc:
        return error(str(exc), 400)
    except Exception as exc:  # noqa: BLE001
        return error(str(exc), 500)


@router.delete("/{sandbox_id}/files")
def delete_files(
    sandbox_id: str,
    path: str = Query(...),
    recursive: bool = Query(default=False),
    container: Annotated[Container, Depends(get_container)] = None,
):
    try:
        result = container.workspace_service.delete_path(sandbox_id, path, recursive)
        return ok(data=result)
    except ValueError as exc:
        return error(str(exc), 400)
    except Exception as exc:  # noqa: BLE001
        return error(str(exc), 500)


@router.post("/{sandbox_id}/renew")
def renew_sandbox_ttl(
    sandbox_id: str,
    body: dict | None = None,
    container: Annotated[Container, Depends(get_container)] = None,
) -> JSONResponse:
    ttl = (body or {}).get("ttl", 0)
    try:
        container.pool_service.renew_sandbox_ttl(sandbox_id, ttl)
        sandbox = container.sandbox_service.get_sandbox(sandbox_id)
        return ok(data=sandbox, message="Sandbox TTL renewed successfully")
    except Exception as exc:  # noqa: BLE001
        return error(str(exc), 500)


@router.put("/{sandbox_id}/ttl")
def update_sandbox_ttl(
    sandbox_id: str,
    body: dict,
    container: Annotated[Container, Depends(get_container)],
) -> JSONResponse:
    try:
        container.pool_service.update_sandbox_ttl(sandbox_id, body["ttl_seconds"])
        sandbox = container.sandbox_service.get_sandbox(sandbox_id)
        return ok(data=sandbox, message="Sandbox TTL updated successfully")
    except KeyError as exc:
        return error(f"Invalid request body: {exc}", 400)
    except Exception as exc:  # noqa: BLE001
        return error(str(exc), 500)


@router.get("/{sandbox_id}/ttl")
def get_sandbox_ttl(
    sandbox_id: str,
    container: Annotated[Container, Depends(get_container)],
) -> JSONResponse:
    try:
        sandbox = container.sandbox_service.get_sandbox(sandbox_id)
        return ok(
            data={
                "ttl_seconds": sandbox.ttl_seconds,
                "expires_at": sandbox.expires_at,
                "time_remaining": sandbox.time_remaining_seconds,
                "ttl_enabled": sandbox.expires_at is not None,
            }
        )
    except Exception:
        return error("Sandbox not found", 404)


@router.get("/{sandbox_id}/status")
def get_sandbox_status(
    sandbox_id: str,
    container: Annotated[Container, Depends(get_container)],
) -> JSONResponse:
    try:
        return ok(data=container.sandbox_service.get_sandbox(sandbox_id))
    except Exception:
        return error("Sandbox not found", 404)
