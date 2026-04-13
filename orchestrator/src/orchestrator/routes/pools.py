from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from orchestrator.container import Container
from orchestrator.deps import get_container
from orchestrator.domain.models import CreatePoolRequest, UpdatePoolRequest
from orchestrator.responses import error, ok

router = APIRouter(prefix="/api/v1/pools", tags=["pools"])


@router.post("/{template_id}")
def create_pool(
    template_id: str,
    request: CreatePoolRequest,
    container: Annotated[Container, Depends(get_container)],
) -> JSONResponse:
    try:
        status = container.pool_service.create_pool(template_id, request)
        return ok(data=status, message="Pool created successfully", status_code=201)
    except ValueError as exc:
        return error(str(exc), 400)
    except Exception as exc:  # noqa: BLE001
        return error(str(exc), 500)


@router.get("")
def list_pools(container: Annotated[Container, Depends(get_container)]) -> JSONResponse:
    try:
        return ok(data=container.pool_service.list_pools())
    except Exception as exc:  # noqa: BLE001
        return error("Failed to list pools", 500)


@router.get("/{template_id}")
def get_pool(
    template_id: str,
    container: Annotated[Container, Depends(get_container)],
) -> JSONResponse:
    try:
        return ok(data=container.pool_service.get_pool_status(template_id))
    except Exception:
        return error("Pool not found", 404)


@router.put("/{template_id}")
def update_pool(
    template_id: str,
    request: UpdatePoolRequest,
    container: Annotated[Container, Depends(get_container)],
) -> JSONResponse:
    try:
        status = container.pool_service.update_pool(template_id, request)
        return ok(data=status, message="Pool updated successfully")
    except ValueError as exc:
        return error(str(exc), 400)
    except Exception as exc:  # noqa: BLE001
        return error(str(exc), 500)


@router.delete("/{template_id}")
def delete_pool(
    template_id: str,
    container: Annotated[Container, Depends(get_container)],
) -> JSONResponse:
    try:
        container.pool_service.delete_pool(template_id)
        return ok(message="Pool deleted successfully")
    except Exception as exc:  # noqa: BLE001
        return error(str(exc), 500)
