from __future__ import annotations

from collections.abc import AsyncIterator
from time import monotonic

import httpx
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask
from starlette.requests import Request

from orchestrator.config import Settings
from orchestrator.infra.kubernetes import KubernetesGateway


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

    async def proxy(
        self,
        sandbox_id: str,
        envd_path: str,
        request: Request,
    ) -> StreamingResponse:
        pod_ip = self._get_pod_ip(sandbox_id)
        client = self._get_client()

        try:
            upstream = await self._send(client, pod_ip, envd_path, request)
        except httpx.RequestError as exc:
            self._invalidate_pod_ip(sandbox_id, pod_ip)
            if not self._can_retry(request, exc):
                raise EnvdUpstreamUnavailableError("envd upstream unavailable") from exc
            retry_pod_ip = self._get_pod_ip(sandbox_id, force_refresh=True)
            try:
                upstream = await self._send(client, retry_pod_ip, envd_path, request)
            except httpx.RequestError as retry_exc:
                self._invalidate_pod_ip(sandbox_id, retry_pod_ip)
                raise EnvdUpstreamUnavailableError("envd upstream unavailable") from retry_exc

        closed = False

        async def close_upstream() -> None:
            nonlocal closed
            if closed:
                return
            closed = True
            await upstream.aclose()

        async def body() -> AsyncIterator[bytes]:
            try:
                async for chunk in upstream.aiter_raw():
                    yield chunk
            finally:
                await close_upstream()

        response = StreamingResponse(
            body(),
            status_code=upstream.status_code,
            background=BackgroundTask(close_upstream),
        )
        response.raw_headers = _filter_headers(
            list(upstream.headers.raw),
            request_headers=False,
        )
        return response
