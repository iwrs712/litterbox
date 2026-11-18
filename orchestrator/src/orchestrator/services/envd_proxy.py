from __future__ import annotations

import json
import logging
import time
import urllib.request
from collections.abc import AsyncIterator
from time import monotonic

import httpx
from fastapi.responses import Response, StreamingResponse
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from starlette.background import BackgroundTask
from starlette.requests import Request

from orchestrator.config import Settings
from orchestrator.infra.kubernetes import KubernetesGateway
from orchestrator.services.metrics import sandbox_metrics
from orchestrator.telemetry import normalize_envd_path

logger = logging.getLogger(__name__)


class EnvdUpstreamUnavailableError(RuntimeError):
    pass


_HOP_BY_HOP_HEADERS = {
    b"connection",
    b"keep-alive",
    b"proxy-authenticate",
    b"proxy-authorization",
    b"te",
    b"trailer",
    b"transfer-encoding",
    b"upgrade",
}

# Small JSON error responses (e.g. envd's {"code": "restoring_workspace"})
# are buffered so their error code can be attached to the span and metrics.
_MAX_JSON_BUFFER = 64 * 1024


def _connection_header_tokens(headers: list[tuple[bytes, bytes]]) -> set[bytes]:
    tokens: set[bytes] = set()
    for name, value in headers:
        if name.lower() != b"connection":
            continue
        tokens.update(token.strip().lower() for token in value.split(b",") if token.strip())
    return tokens


def _filter_headers(
    headers: list[tuple[bytes, bytes]],
    *,
    request_headers: bool,
) -> list[tuple[bytes, bytes]]:
    blocked = _HOP_BY_HOP_HEADERS | _connection_header_tokens(headers)
    if request_headers:
        blocked |= {b"authorization", b"host"}
    return [(name, value) for name, value in headers if name.lower() not in blocked]


class EnvdProxyService:
    def __init__(
        self,
        settings: Settings,
        gateway: KubernetesGateway,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.gateway = gateway
        self.transport = transport
        self._client: httpx.AsyncClient | None = None
        self._pod_ip_cache: dict[str, tuple[str, float]] = {}

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    None,
                    connect=self.settings.envd.connect_timeout_seconds,
                ),
                trust_env=False,
                transport=self.transport,
            )
        return self._client

    def _get_pod_ip(self, sandbox_id: str, *, force_refresh: bool = False) -> str:
        now = monotonic()
        cached = self._pod_ip_cache.get(sandbox_id)
        if not force_refresh and cached is not None:
            pod_ip, expires_at = cached
            if expires_at > now:
                return pod_ip
            self._pod_ip_cache.pop(sandbox_id, None)

        pod_ip = self.gateway.get_ready_pod_ip(sandbox_id)
        ttl = self.settings.envd.pod_ip_cache_ttl_seconds
        if ttl > 0:
            max_entries = max(self.settings.sandbox.max_sandboxes, 1)
            if sandbox_id not in self._pod_ip_cache and len(self._pod_ip_cache) >= max_entries:
                self._pod_ip_cache.pop(next(iter(self._pod_ip_cache)))
            self._pod_ip_cache[sandbox_id] = (pod_ip, now + ttl)
        return pod_ip

    def _invalidate_pod_ip(self, sandbox_id: str, pod_ip: str) -> None:
        cached = self._pod_ip_cache.get(sandbox_id)
        if cached is not None and cached[0] == pod_ip:
            self._pod_ip_cache.pop(sandbox_id, None)

    def _build_url(self, pod_ip: str, envd_path: str, request: Request) -> httpx.URL:
        return httpx.URL(
            scheme="http",
            host=pod_ip,
            port=self.settings.envd.port,
            path=f"/{envd_path}",
        ).copy_with(query=request.scope.get("query_string", b""))

    async def _send(
        self,
        client: httpx.AsyncClient,
        pod_ip: str,
        envd_path: str,
        request: Request,
    ) -> httpx.Response:
        upstream_request = client.build_request(
            request.method,
            self._build_url(pod_ip, envd_path, request),
            headers=_filter_headers(list(request.headers.raw), request_headers=True),
            content=request.stream(),
        )
        return await client.send(upstream_request, stream=True)

    @staticmethod
    def _can_retry(request: Request, exc: httpx.RequestError) -> bool:
        if not isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
            return False
        if request.method.upper() not in {"GET", "HEAD", "OPTIONS"}:
            return False
        return request.headers.get("content-length") in {None, "0"} and "transfer-encoding" not in request.headers

    async def aclose(self) -> None:
        client = self._client
        self._client = None
        self._pod_ip_cache.clear()
        if client is not None:
            await client.aclose()

    def ensure_workspace_restored(self, sandbox_id: str) -> None:
        """Open the envd workspace gate after a Pod start.

        The sandbox-agent sidecar refuses process/filesystem calls until
        ``POST /v1/workspace/restore`` has been called. With no object-storage
        prefix configured, its local mode treats the mounted PVC as the
        workspace and marks it ready immediately.
        """
        pod_ip = self._get_pod_ip(sandbox_id, force_refresh=True)
        request = urllib.request.Request(
            f"http://{pod_ip}:{self.settings.envd.port}/v1/workspace/restore",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        timeout = max(self.settings.envd.connect_timeout_seconds, 5.0)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read()

    async def proxy(
        self,
        sandbox_id: str,
        envd_path: str,
        request: Request,
    ) -> StreamingResponse:
        tracer = trace.get_tracer(__name__)
        span = tracer.start_span("envd.proxy")
        started_at = time.perf_counter()
        normalized_path = normalize_envd_path(envd_path)
        pod_ip = ""
        status_code: int | None = None
        finished = False

        span.set_attribute("litterbox.sandbox.id", sandbox_id)
        span.set_attribute("litterbox.envd.path", normalized_path)
        span.set_attribute("http.request.method", request.method)

        def finish(*, error: str | None = None) -> None:
            nonlocal finished
            if finished:
                return
            finished = True
            duration = time.perf_counter() - started_at
            outcome = (
                "success"
                if error is None and (status_code is None or status_code < 500)
                else "error"
            )
            span.set_attribute("litterbox.outcome", outcome)
            if error is not None:
                span.set_attribute("error.type", error)
            if outcome == "error":
                span.set_status(Status(StatusCode.ERROR, error or f"HTTP {status_code}"))
            span.end()
            sandbox_metrics.record_proxy(
                method=request.method.upper(),
                envd_path=normalized_path,
                duration=duration,
                status_code=status_code,
                error=error,
            )

        try:
            pod_ip = self._get_pod_ip(sandbox_id)
            client = self._get_client()

            try:
                upstream = await self._send(client, pod_ip, envd_path, request)
            except httpx.RequestError as exc:
                self._invalidate_pod_ip(sandbox_id, pod_ip)
                if not self._can_retry(request, exc):
                    logger.warning(
                        "envd upstream unavailable sandbox_id=%s path=%s error=%s",
                        sandbox_id,
                        normalized_path,
                        exc,
                    )
                    raise EnvdUpstreamUnavailableError("envd upstream unavailable") from exc
                retry_pod_ip = self._get_pod_ip(sandbox_id, force_refresh=True)
                try:
                    upstream = await self._send(client, retry_pod_ip, envd_path, request)
                except httpx.RequestError as retry_exc:
                    self._invalidate_pod_ip(sandbox_id, retry_pod_ip)
                    logger.warning(
                        "envd upstream unavailable after retry sandbox_id=%s path=%s error=%s",
                        sandbox_id,
                        normalized_path,
                        retry_exc,
                    )
                    raise EnvdUpstreamUnavailableError("envd upstream unavailable") from retry_exc
        except Exception as exc:  # noqa: BLE001
            finish(error=type(exc).__name__)
            if not isinstance(exc, EnvdUpstreamUnavailableError):
                logger.warning(
                    "envd proxy failed sandbox_id=%s path=%s error=%s",
                    sandbox_id,
                    normalized_path,
                    exc,
                )
            raise

        status_code = upstream.status_code
        span.set_attribute("litterbox.pod.ip", pod_ip)
        span.set_attribute("http.response.status_code", status_code)

        content_type = upstream.headers.get("content-type", "").lower()
        content_length = upstream.headers.get("content-length")
        if "application/json" in content_type and content_length is not None:
            try:
                length = int(content_length)
            except ValueError:
                length = -1
            if 0 <= length <= _MAX_JSON_BUFFER:
                body_bytes = await upstream.aread()
                await upstream.aclose()
                span.set_attribute("http.response.body.size", len(body_bytes))
                error_code: str | None = None
                try:
                    payload = json.loads(body_bytes)
                except (ValueError, UnicodeDecodeError):
                    payload = None
                if isinstance(payload, dict):
                    code = payload.get("code")
                    if code and str(code).lower() not in {"ok", "success"}:
                        error_code = str(code)
                        message = str(payload.get("message", ""))[:256]
                        span.set_attribute("litterbox.envd.error_code", error_code)
                        if message:
                            span.set_attribute("litterbox.envd.error_message", message)
                        logger.warning(
                            "envd upstream error sandbox_id=%s path=%s code=%s message=%s",
                            sandbox_id,
                            normalized_path,
                            error_code,
                            message,
                        )
                finish(error=error_code)
                response = Response(content=body_bytes, status_code=upstream.status_code)
                response.raw_headers = _filter_headers(
                    list(upstream.headers.raw),
                    request_headers=False,
                )
                return response

        closed = False

        async def close_upstream() -> None:
            nonlocal closed
            if closed:
                return
            closed = True
            await upstream.aclose()

        async def body() -> AsyncIterator[bytes]:
            body_bytes = 0
            stream_error: str | None = None
            try:
                async for chunk in upstream.aiter_raw():
                    body_bytes += len(chunk)
                    yield chunk
            except Exception as exc:  # noqa: BLE001
                stream_error = type(exc).__name__
                raise
            finally:
                span.set_attribute("http.response.body.size", body_bytes)
                await close_upstream()
                finish(error=stream_error)

        async def background() -> None:
            await close_upstream()
            finish()

        response = StreamingResponse(
            body(),
            status_code=upstream.status_code,
            background=BackgroundTask(background),
        )
        response.raw_headers = _filter_headers(
            list(upstream.headers.raw),
            request_headers=False,
        )
        return response
