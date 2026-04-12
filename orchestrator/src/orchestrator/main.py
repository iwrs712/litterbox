from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
import json
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from orchestrator.auth import is_http_authorized, is_websocket_authorized, normalize_configured_token
from orchestrator.container import Container, build_container
from orchestrator.domain.models import (
    AllocateSandboxRequest,
    ApiResponse,
    CreatePoolRequest,
    CreateServiceExposeRequest,
    CreateTemplateRequest,
    CreateWebhookRequest,
    ExecCommandRequest,
    FileKind,
    FileView,
    PoolListResponse,
    QueryOptions,
    TemplateListParams,
    UpdatePoolRequest,
    UpdateSandboxRequest,
    UpdateTemplateRequest,
    UpdateWebhookRequest,
    WebhookListParams,
)
from orchestrator.utils import validate_metadata_key


logger = logging.getLogger(__name__)
API_PREFIX = "/api/v1"


def ok(*, data=None, message: str | None = None, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=ApiResponse(success=True, data=data, message=message).model_dump(mode="json", exclude_none=True),
    )


def error(message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=ApiResponse(success=False, error=message).model_dump(mode="json", exclude_none=True),
    )


def parse_timeout(timeout: str | None) -> int:
    if not timeout:
        return 10
    try:
        if timeout.endswith("s"):
            value = int(timeout[:-1])
        elif timeout.endswith("m"):
            value = int(timeout[:-1]) * 60
        elif timeout.endswith("h"):
            value = int(timeout[:-1]) * 3600
        else:
            value = int(timeout)
        return max(1, min(value, 3600))
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="invalid timeout format, use e.g. 30s, 5m, 1h")


def validate_metadata(metadata: dict[str, str] | None) -> None:
    if not metadata:
        return
    for key in metadata:
        validate_metadata_key(key)


def get_container() -> Container:
    return app.state.container


@asynccontextmanager
async def lifespan(_: FastAPI):
    app.state.container = build_container()
    yield


app = FastAPI(title="Litterbox Orchestrator", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def enforce_bearer_auth(request: Request, call_next):
    if not request.url.path.startswith(API_PREFIX):
        return await call_next(request)
    if request.method == "OPTIONS":
        return await call_next(request)
    container: Container | None = getattr(app.state, "container", None)
    expected_token = ""
    if container is not None:
        expected_token = normalize_configured_token(container.settings.auth.bearer_token)
    if is_http_authorized(expected_token, request.headers.get("Authorization")):
        return await call_next(request)
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        headers={"WWW-Authenticate": "Bearer"},
        content=ApiResponse(success=False, error="Unauthorized").model_dump(mode="json", exclude_none=True),
    )


# Prometheus /metrics 端点（供 Prometheus scrape 使用）
from prometheus_client import make_asgi_app as _make_metrics_app  # noqa: E402
app.mount("/metrics", _make_metrics_app())


@app.get("/")
def root() -> JSONResponse:
    return JSONResponse(status_code=200, content={"message": "Litterbox API is running", "version": "1.0.0"})


@app.get("/health")
def health() -> JSONResponse:
    return ok(message="Litterbox API is running")


@app.post("/api/v1/templates")
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


@app.get("/api/v1/templates")
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


@app.get("/api/v1/templates/{template_id}")
def get_template(template_id: str, container: Annotated[Container, Depends(get_container)]) -> JSONResponse:
    try:
        return ok(data=container.template_service.get_template(template_id))
    except Exception as exc:  # noqa: BLE001
        return error(str(exc), 404 if "not found" in str(exc) else 500)


@app.patch("/api/v1/templates/{template_id}")
def update_template(
    template_id: str,
    request: UpdateTemplateRequest,
    container: Annotated[Container, Depends(get_container)],
) -> JSONResponse:
    try:
        return ok(data=container.template_service.update_template(template_id, request))
    except Exception as exc:  # noqa: BLE001
        return error(str(exc), 404 if "not found" in str(exc) else 500)


@app.delete("/api/v1/templates/{template_id}")
def delete_template(template_id: str, container: Annotated[Container, Depends(get_container)]) -> JSONResponse:
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


@app.post("/api/v1/sandboxes")
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


@app.get("/api/v1/sandboxes")
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


@app.post("/api/v1/sandboxes/query")
def query_sandboxes(
    request: QueryOptions,
    container: Annotated[Container, Depends(get_container)],
) -> JSONResponse:
    try:
        return ok(data=container.sandbox_service.list_sandboxes(request))
    except Exception as exc:  # noqa: BLE001
        return error(str(exc), 500)


@app.get("/api/v1/sandboxes/{sandbox_id}")
def get_sandbox(sandbox_id: str, container: Annotated[Container, Depends(get_container)]) -> JSONResponse:
    try:
        return ok(data=container.sandbox_service.get_sandbox(sandbox_id))
    except Exception:
        return error("Sandbox not found", 404)


@app.patch("/api/v1/sandboxes/{sandbox_id}")
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


@app.delete("/api/v1/sandboxes/{sandbox_id}")
def delete_sandbox(sandbox_id: str, container: Annotated[Container, Depends(get_container)]) -> JSONResponse:
    try:
        container.pool_service.release_sandbox(sandbox_id)
        return ok(message="Sandbox deleted successfully")
    except Exception as exc:  # noqa: BLE001
        return error(str(exc), 500)


@app.post("/api/v1/sandboxes/{sandbox_id}/start")
def start_sandbox(sandbox_id: str, container: Annotated[Container, Depends(get_container)]) -> JSONResponse:
    try:
        container.sandbox_service.start_sandbox(sandbox_id)
        return ok(message="Sandbox started successfully")
    except Exception as exc:  # noqa: BLE001
        return error(str(exc), 500)


@app.post("/api/v1/sandboxes/{sandbox_id}/stop")
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


@app.post("/api/v1/sandboxes/{sandbox_id}/restart")
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


@app.post("/api/v1/sandboxes/{sandbox_id}/exec")
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


@app.get("/api/v1/sandboxes/{sandbox_id}/files")
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


@app.put("/api/v1/sandboxes/{sandbox_id}/files")
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


@app.delete("/api/v1/sandboxes/{sandbox_id}/files")
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


@app.post("/api/v1/sandboxes/{sandbox_id}/renew")
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


@app.put("/api/v1/sandboxes/{sandbox_id}/ttl")
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


@app.get("/api/v1/sandboxes/{sandbox_id}/ttl")
def get_sandbox_ttl(sandbox_id: str, container: Annotated[Container, Depends(get_container)]) -> JSONResponse:
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


@app.get("/api/v1/sandboxes/{sandbox_id}/status")
def get_sandbox_status(sandbox_id: str, container: Annotated[Container, Depends(get_container)]) -> JSONResponse:
    try:
        return ok(data=container.sandbox_service.get_sandbox(sandbox_id))
    except Exception:
        return error("Sandbox not found", 404)


@app.post("/api/v1/pools/{template_id}")
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


@app.get("/api/v1/pools")
def list_pools(container: Annotated[Container, Depends(get_container)]) -> JSONResponse:
    try:
        return ok(data=container.pool_service.list_pools())
    except Exception as exc:  # noqa: BLE001
        return error("Failed to list pools", 500)


@app.get("/api/v1/pools/{template_id}")
def get_pool(template_id: str, container: Annotated[Container, Depends(get_container)]) -> JSONResponse:
    try:
        return ok(data=container.pool_service.get_pool_status(template_id))
    except Exception:
        return error("Pool not found", 404)


@app.put("/api/v1/pools/{template_id}")
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


@app.delete("/api/v1/pools/{template_id}")
def delete_pool(template_id: str, container: Annotated[Container, Depends(get_container)]) -> JSONResponse:
    try:
        container.pool_service.delete_pool(template_id)
        return ok(message="Pool deleted successfully")
    except Exception as exc:  # noqa: BLE001
        return error(str(exc), 500)


@app.post("/api/v1/sandboxes/{sandbox_id}/exposes")
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


@app.get("/api/v1/sandboxes/{sandbox_id}/exposes")
def list_exposes(sandbox_id: str, container: Annotated[Container, Depends(get_container)]) -> JSONResponse:
    try:
        exposes = container.expose_service.list_exposes(sandbox_id)
        return ok(data={"exposes": [item.model_dump(mode="json") for item in exposes], "total": len(exposes)})
    except Exception as exc:  # noqa: BLE001
        return error(str(exc), 500)


@app.get("/api/v1/exposes/{expose_id}")
def get_expose(expose_id: str, container: Annotated[Container, Depends(get_container)]) -> JSONResponse:
    try:
        return ok(data=container.expose_service.get_expose(expose_id))
    except Exception:
        return error("Expose not found", 404)


@app.delete("/api/v1/exposes/{expose_id}")
def delete_expose(expose_id: str, container: Annotated[Container, Depends(get_container)]) -> JSONResponse:
    try:
        container.expose_service.delete_expose(expose_id)
        return ok(message="Expose deleted successfully")
    except Exception as exc:  # noqa: BLE001
        return error(str(exc), 500)


@app.post("/api/v1/webhooks")
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


@app.get("/api/v1/webhooks")
def list_webhooks(
    user_id: str = "",
    container: Annotated[Container, Depends(get_container)] = None,
) -> JSONResponse:
    try:
        return ok(data=container.webhook_service.list_webhooks(WebhookListParams(user_id=user_id)))
    except Exception as exc:  # noqa: BLE001
        return error(str(exc), 500)


@app.get("/api/v1/webhooks/{webhook_id}")
def get_webhook(webhook_id: str, container: Annotated[Container, Depends(get_container)]) -> JSONResponse:
    try:
        return ok(data=container.webhook_service.get_webhook(webhook_id))
    except Exception as exc:  # noqa: BLE001
        return error(str(exc), 404)


@app.patch("/api/v1/webhooks/{webhook_id}")
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


@app.delete("/api/v1/webhooks/{webhook_id}")
def delete_webhook(webhook_id: str, container: Annotated[Container, Depends(get_container)]) -> JSONResponse:
    try:
        container.webhook_service.delete_webhook(webhook_id)
        return ok(message="Webhook deleted successfully")
    except Exception as exc:  # noqa: BLE001
        return error(str(exc), 500)


@app.get("/api/v1/metrics/snapshot")
def get_metrics_snapshot(container: Annotated[Container, Depends(get_container)]) -> JSONResponse:
    """返回沙盒创建指标快照（供前端 dashboard 轮询，JSON 格式）。"""
    try:
        from orchestrator.services.metrics import sandbox_metrics
        from orchestrator.services.sandboxes import SandboxService
        # 注入实时状态，省去前端再单独调 /stats
        deployments = container.gateway.list_deployments("component=sandbox")
        running = stopped = creating = 0
        for dep in deployments:
            s = SandboxService._deployment_status_to_sandbox_status(dep).value
            if s == "running":
                running += 1
            elif s in {"stopped", "exited"}:
                stopped += 1
            elif s == "created":
                creating += 1
        sandbox_metrics.set_live_stats({
            "total": len(deployments),
            "running": running,
            "stopped": stopped,
            "creating": creating,
        })
        return ok(data=sandbox_metrics.snapshot())
    except Exception as exc:  # noqa: BLE001
        return error(str(exc), 500)


async def require_websocket_auth(websocket: WebSocket, container: Container) -> bool:
    expected_token = normalize_configured_token(container.settings.auth.bearer_token)
    authorized = is_websocket_authorized(
        expected_token,
        websocket.headers.get("authorization"),
        websocket.query_params.get("token"),
    )
    if authorized:
        return True
    await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="unauthorized")
    return False


@app.websocket("/api/v1/sandboxes/{sandbox_id}/terminal")
async def terminal(websocket: WebSocket, sandbox_id: str) -> None:
    container: Container = app.state.container
    if not await require_websocket_auth(websocket, container):
        return
    await websocket.accept()
    try:
        session = container.gateway.open_shell(sandbox_id)
    except Exception:  # noqa: BLE001
        logger.exception("failed to open terminal session for sandbox %s", sandbox_id)
        await websocket.close(code=1011, reason="failed to open terminal session")
        return
    stop = asyncio.Event()
    terminal_size = {"cols": 80, "rows": 24}

    def write_resize() -> None:
        session.write_channel(4, json.dumps({"Width": terminal_size["cols"], "Height": terminal_size["rows"]}))

    async def send_output() -> None:
        try:
            while not stop.is_set() and session.is_open():
                await asyncio.to_thread(session.update, 1)
                if session.peek_stdout():
                    await websocket.send_json({"type": "stdout", "data": session.read_stdout()})
                if session.peek_stderr():
                    await websocket.send_json({"type": "stderr", "data": session.read_stderr()})
                await asyncio.sleep(0.05)
            if not stop.is_set():
                logger.warning("terminal exec stream closed for sandbox %s", sandbox_id)
        except Exception:  # noqa: BLE001
            logger.exception("terminal send_output failed for sandbox %s", sandbox_id)
            raise

    async def receive_input() -> None:
        try:
            while not stop.is_set():
                try:
                    message = await websocket.receive_json()
                except WebSocketDisconnect:
                    stop.set()
                    return
                msg_type = message.get("type")
                if msg_type == "stdin":
                    session.write_stdin(message.get("data", ""))
                elif msg_type == "resize":
                    terminal_size["cols"] = message.get("cols", 80)
                    terminal_size["rows"] = message.get("rows", 24)
                    write_resize()
        except Exception:  # noqa: BLE001
            logger.exception("terminal receive_input failed for sandbox %s", sandbox_id)
            raise

    sender = asyncio.create_task(send_output())
    receiver = asyncio.create_task(receive_input())
    try:
        done, pending = await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            with suppress(asyncio.CancelledError):
                await task
        for task in pending:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
    finally:
        stop.set()
        session.close()


@app.websocket("/api/v1/sandboxes/{sandbox_id}/acp")
async def acp(websocket: WebSocket, sandbox_id: str) -> None:
    container: Container = app.state.container
    if not await require_websocket_auth(websocket, container):
        return
    await websocket.accept()
    try:
        session = container.gateway.open_acp(sandbox_id)
    except Exception:  # noqa: BLE001
        logger.exception("failed to open acp session for sandbox %s", sandbox_id)
        await websocket.close(code=1011, reason="failed to open acp session")
        return

    stop = asyncio.Event()

    async def send_output() -> None:
        try:
            while not stop.is_set() and session.is_open():
                await asyncio.to_thread(session.update, 1)
                if session.peek_stdout():
                    await websocket.send_text(session.read_stdout())
                if session.peek_stderr():
                    logger.warning("acp stderr sandbox=%s: %s", sandbox_id, session.read_stderr().strip())
                await asyncio.sleep(0.05)
            if not stop.is_set():
                logger.warning("acp exec stream closed for sandbox %s", sandbox_id)
        except Exception:  # noqa: BLE001
            logger.exception("acp send_output failed for sandbox %s", sandbox_id)
            raise

    async def receive_input() -> None:
        try:
            while not stop.is_set():
                try:
                    message = await websocket.receive_text()
                except WebSocketDisconnect:
                    stop.set()
                    return
                session.write_stdin(message)
        except Exception:  # noqa: BLE001
            logger.exception("acp receive_input failed for sandbox %s", sandbox_id)
            raise

    sender = asyncio.create_task(send_output())
    receiver = asyncio.create_task(receive_input())
    try:
        done, pending = await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            with suppress(asyncio.CancelledError):
                await task
        for task in pending:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
    finally:
        stop.set()
        session.close()
