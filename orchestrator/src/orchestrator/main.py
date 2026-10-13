from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from orchestrator.auth import is_e2b_authorized, is_http_authorized, normalize_configured_token
from orchestrator.container import Container, build_container
from orchestrator.domain.models import ApiResponse
from orchestrator.responses import ok
from orchestrator.routes import e2b, envd, exposes, metrics, pools, sandboxes, templates, webhooks

logger = logging.getLogger(__name__)
API_PREFIX = "/api/v1"
ENVD_PROXY_PREFIX = f"{API_PREFIX}/sandboxes/"


def _is_envd_proxy_path(path: str) -> bool:
    if not path.startswith(ENVD_PROXY_PREFIX):
        return False
    sandbox_id, separator, suffix = path[len(ENVD_PROXY_PREFIX) :].partition("/")
    return bool(
        sandbox_id
        and separator
        and (suffix == "envd" or suffix.startswith("envd/"))
    )


def _is_cors_preflight(request: Request) -> bool:
    return bool(
        request.headers.get("Origin")
        and request.headers.get("Access-Control-Request-Method")
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    container = build_container()
    app.state.container = container
    try:
        yield
    finally:
        envd_proxy_service = getattr(container, "envd_proxy_service", None)
        close_envd_proxy = getattr(envd_proxy_service, "aclose", None)
        if close_envd_proxy is not None:
            await close_envd_proxy()


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
    if request.scope.get("litterbox.e2b_envd_host"):
        container: Container | None = getattr(app.state, "container", None)
        expected_key = ""
        if container is not None:
            expected_key = normalize_configured_token(
                container.settings.e2b.api_key or container.settings.auth.bearer_token
            )
        if is_e2b_authorized(
            expected_key,
            request.headers.get("X-API-Key"),
            request.headers.get("Authorization"),
            request.headers.get("X-Access-Token"),
        ):
            return await call_next(request)
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Bearer"},
            content={"code": "unauthorized", "message": "Unauthorized"},
        )
    if not request.url.path.startswith(API_PREFIX):
        if not request.url.path.startswith("/e2b"):
            return await call_next(request)
        container: Container | None = getattr(app.state, "container", None)
        expected_key = ""
        if container is not None:
            expected_key = normalize_configured_token(
                container.settings.e2b.api_key or container.settings.auth.bearer_token
            )
        if is_e2b_authorized(
            expected_key,
            request.headers.get("X-API-Key"),
            request.headers.get("Authorization"),
            request.headers.get("X-Access-Token"),
        ):
            return await call_next(request)
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Bearer"},
            content={"code": "unauthorized", "message": "Unauthorized"},
        )
    if request.method == "OPTIONS" and (
        not _is_envd_proxy_path(request.url.path) or _is_cors_preflight(request)
    ):
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


@app.middleware("http")
async def rewrite_e2b_sandbox_host(request: Request, call_next):
    container: Container | None = getattr(app.state, "container", None)
    if (
        container is not None
        and container.settings.e2b.enabled
        and not request.url.path.startswith(("/api/v1", "/e2b"))
    ):
        sandbox_id = envd.parse_sandbox_envd_host(
            request.headers.get("host"),
            container.settings.e2b.domain,
            container.settings.envd.port,
        )
        if sandbox_id:
            original_path = request.scope.get("path", "") or "/"
            request.scope["litterbox.e2b_envd_host"] = True
            request.scope["path"] = f"/api/v1/sandboxes/{sandbox_id}/envd{original_path}"
            request.scope["raw_path"] = request.scope["path"].encode()
    return await call_next(request)


# Prometheus /metrics 端点（供 Prometheus scrape 使用）
from prometheus_client import make_asgi_app as _make_metrics_app  # noqa: E402
app.mount("/metrics", _make_metrics_app())

# Routers
app.include_router(templates.router)
app.include_router(sandboxes.router)
app.include_router(pools.router)
app.include_router(exposes.router)
app.include_router(webhooks.router)
app.include_router(metrics.router)
app.include_router(envd.router)
app.include_router(e2b.router)


@app.get("/")
def root() -> JSONResponse:
    return JSONResponse(status_code=200, content={"message": "Litterbox API is running", "version": "1.0.0"})


@app.get("/health")
def health() -> JSONResponse:
    return ok(message="Litterbox API is running")
