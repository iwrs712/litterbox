from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from orchestrator.container import Container
from orchestrator.deps import get_container
from orchestrator.domain.models import CreateServiceExposeRequest
from orchestrator.responses import error, ok

router = APIRouter(tags=["exposes"])


@router.post("/api/v1/sandboxes/{sandbox_id}/exposes")
def create_expose(
    sandbox_id: str,
    request: CreateServiceExposeRequest,
    container: Annotated[Container, Depends(get_container)],
) -> JSONResponse:
    try:
        request.sandbox_id = sandbox_id
        expose = container.expose_service.create_expose(request)
        return ok(data=expose, message="Service exposed successfully", status_code=201)
    except ValueError as exc:
        return error(str(exc), 400)
    except Exception as exc:  # noqa: BLE001
        return error(str(exc), 500)


@router.get("/api/v1/sandboxes/{sandbox_id}/exposes")
def list_exposes(
    sandbox_id: str,
    container: Annotated[Container, Depends(get_container)],
) -> JSONResponse:
    try:
        exposes = container.expose_service.list_exposes(sandbox_id)
        return ok(data={"exposes": [item.model_dump(mode="json") for item in exposes], "total": len(exposes)})
    except Exception as exc:  # noqa: BLE001
        return error(str(exc), 500)


@router.get("/api/v1/exposes/{expose_id}")
def get_expose(
    expose_id: str,
    container: Annotated[Container, Depends(get_container)],
) -> JSONResponse:
    try:
        return ok(data=container.expose_service.get_expose(expose_id))
    except Exception:
        return error("Expose not found", 404)


@router.delete("/api/v1/exposes/{expose_id}")
def delete_expose(
    expose_id: str,
    container: Annotated[Container, Depends(get_container)],
) -> JSONResponse:
    try:
        container.expose_service.delete_expose(expose_id)
        return ok(message="Expose deleted successfully")
    except Exception as exc:  # noqa: BLE001
        return error(str(exc), 500)
