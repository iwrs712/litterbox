from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from orchestrator.container import Container
from orchestrator.deps import get_container
from orchestrator.domain.models import CreateTemplateRequest, TemplateListParams, UpdateTemplateRequest
from orchestrator.responses import error, ok

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/templates", tags=["templates"])


@router.post("")
def create_template(
    request: CreateTemplateRequest,
    container: Annotated[Container, Depends(get_container)],
) -> JSONResponse:
    try:
        return ok(data=container.template_service.create_template(request), status_code=201)
    except ValueError as exc:
        return error(str(exc), 400)
    except Exception as exc:  # noqa: BLE001
        return error(str(exc), 500)


@router.get("")
def list_templates(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    name: str = "",
    user_id: str = "",
    container: Annotated[Container, Depends(get_container)] = None,
) -> JSONResponse:
    params = TemplateListParams(page=page, page_size=page_size, name=name, user_id=user_id)
    try:
        return ok(data=container.template_service.list_templates(params))
    except Exception as exc:  # noqa: BLE001
        return error(str(exc), 500)


@router.get("/{template_id}")
def get_template(
    template_id: str,
    container: Annotated[Container, Depends(get_container)],
) -> JSONResponse:
    try:
        return ok(data=container.template_service.get_template(template_id))
    except Exception as exc:  # noqa: BLE001
        return error(str(exc), 404 if "not found" in str(exc) else 500)


@router.patch("/{template_id}")
def update_template(
    template_id: str,
    request: UpdateTemplateRequest,
    container: Annotated[Container, Depends(get_container)],
) -> JSONResponse:
    try:
        return ok(data=container.template_service.update_template(template_id, request))
    except Exception as exc:  # noqa: BLE001
        return error(str(exc), 404 if "not found" in str(exc) else 500)


@router.delete("/{template_id}")
def delete_template(
    template_id: str,
    container: Annotated[Container, Depends(get_container)],
) -> JSONResponse:
    try:
        container.template_service.get_template(template_id)
    except Exception:
        return error("Template not found", 404)
    try:
        container.pool_service.delete_pool(template_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("failed to delete pool for template %s: %s", template_id, exc)
    try:
        container.template_service.delete_template(template_id)
        return ok(message="Template deleted successfully")
    except Exception as exc:  # noqa: BLE001
        return error(str(exc), 500)
