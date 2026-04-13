from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from orchestrator.auth import is_http_authorized, normalize_configured_token
from orchestrator.container import Container, build_container
from orchestrator.domain.models import ApiResponse
from orchestrator.responses import ok
from orchestrator.routes import exposes, metrics, pools, sandboxes, templates, webhooks, ws

logger = logging.getLogger(__name__)
API_PREFIX = "/api/v1"


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

# Routers
app.include_router(templates.router)
app.include_router(sandboxes.router)
app.include_router(pools.router)
app.include_router(exposes.router)
app.include_router(webhooks.router)
app.include_router(metrics.router)
app.include_router(ws.router)


@app.get("/")
def root() -> JSONResponse:
    return JSONResponse(status_code=200, content={"message": "Litterbox API is running", "version": "1.0.0"})


@app.get("/health")
def health() -> JSONResponse:
    return ok(message="Litterbox API is running")
