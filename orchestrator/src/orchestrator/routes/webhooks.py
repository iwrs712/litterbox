from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from orchestrator.container import Container
from orchestrator.deps import get_container
from orchestrator.domain.models import CreateWebhookRequest, UpdateWebhookRequest, WebhookListParams
from orchestrator.responses import error, ok

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


@router.post("")
def create_webhook(
    request: CreateWebhookRequest,
    container: Annotated[Container, Depends(get_container)],
) -> JSONResponse:
    try:
        return ok(data=container.webhook_service.create_webhook(request), status_code=201)
    except ValueError as exc:
        return error(str(exc), 400)
    except Exception as exc:  # noqa: BLE001
        return error(str(exc), 500)


@router.get("")
def list_webhooks(
    user_id: str = "",
    container: Annotated[Container, Depends(get_container)] = None,
) -> JSONResponse:
    try:
        return ok(data=container.webhook_service.list_webhooks(WebhookListParams(user_id=user_id)))
    except Exception as exc:  # noqa: BLE001
        return error(str(exc), 500)


@router.get("/{webhook_id}")
def get_webhook(
    webhook_id: str,
    container: Annotated[Container, Depends(get_container)],
) -> JSONResponse:
    try:
        return ok(data=container.webhook_service.get_webhook(webhook_id))
    except Exception as exc:  # noqa: BLE001
        return error(str(exc), 404)


@router.patch("/{webhook_id}")
def update_webhook(
    webhook_id: str,
    request: UpdateWebhookRequest,
    container: Annotated[Container, Depends(get_container)],
) -> JSONResponse:
    try:
        return ok(data=container.webhook_service.update_webhook(webhook_id, request))
    except ValueError as exc:
        return error(str(exc), 400)
    except Exception as exc:  # noqa: BLE001
        return error(str(exc), 500)


@router.delete("/{webhook_id}")
def delete_webhook(
    webhook_id: str,
    container: Annotated[Container, Depends(get_container)],
) -> JSONResponse:
    try:
        container.webhook_service.delete_webhook(webhook_id)
        return ok(message="Webhook deleted successfully")
    except Exception as exc:  # noqa: BLE001
        return error(str(exc), 500)
