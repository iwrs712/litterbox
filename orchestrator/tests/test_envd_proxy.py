from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

import orchestrator.main as main_module
import orchestrator.infra.kubernetes as kubernetes_module
import orchestrator.services.envd_proxy as envd_proxy_module
from orchestrator.config import AuthConfig, EnvdConfig, Settings
from orchestrator.domain.models import SandboxStatus
from orchestrator.infra.kubernetes import (
    KubernetesGateway,
    SandboxNotRunningError,
    SandboxPodAddressUnavailableError,
)
from orchestrator.services.envd_proxy import EnvdProxyService


class RecordingStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.yielded: list[bytes] = []
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            self.yielded.append(chunk)
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


class RecordingTransport(httpx.AsyncBaseTransport):
    def __init__(self, handler) -> None:
        self.handler = handler
        self.closed = False
        self.close_calls = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self.handler(request)

    async def aclose(self) -> None:
        self.close_calls += 1
        self.closed = True


class FakeGateway:
    def __init__(
        self,
        pod_ip: str = "10.42.0.8",
        error: Exception | None = None,
        pod_ips: list[str] | None = None,
    ) -> None:
        self.pod_ips = pod_ips or [pod_ip]
        self.error = error
        self.calls = 0

    def get_ready_pod_ip(self, _sandbox_id: str) -> str:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.pod_ips[min(self.calls - 1, len(self.pod_ips) - 1)]


class FakeSandboxService:
    def __init__(self, status: SandboxStatus = SandboxStatus.RUNNING, missing: bool = False) -> None:
        self.status = status
        self.missing = missing

    def get_sandbox(self, sandbox_id: str):
        if self.missing:
            raise KeyError(sandbox_id)
        return SimpleNamespace(id=sandbox_id, status=self.status)


def make_pod(
    *,
    phase: str = "Running",
    ready: list[bool] | None = None,
    pod_ip: str | None = "10.42.0.8",
    deleting: bool = False,
):
    statuses = None if ready is None else [SimpleNamespace(ready=value) for value in ready]
    return SimpleNamespace(
        metadata=SimpleNamespace(deletion_timestamp="now" if deleting else None),
        status=SimpleNamespace(phase=phase, container_statuses=statuses, pod_ip=pod_ip),
    )


def test_get_ready_pod_ip_selects_only_running_ready_non_deleting_pod() -> None:
    gateway = object.__new__(KubernetesGateway)
    gateway.list_pods = lambda selector: [
        make_pod(deleting=True),
        make_pod(phase="Pending"),
        make_pod(ready=None),
        make_pod(ready=[True, False]),
        make_pod(ready=[True, True], pod_ip="10.42.0.9"),
    ]

    assert gateway.get_ready_pod_ip("sbx-1") == "10.42.0.9"


def test_get_ready_pod_ip_distinguishes_ready_pod_without_address() -> None:
    gateway = object.__new__(KubernetesGateway)
    gateway.list_pods = lambda _selector: [make_pod(ready=[True], pod_ip=None)]

    with pytest.raises(SandboxPodAddressUnavailableError, match="sbx-1"):
        gateway.get_ready_pod_ip("sbx-1")


def test_get_ready_pod_ip_rejects_sandbox_without_ready_pod() -> None:
    gateway = object.__new__(KubernetesGateway)
    gateway.list_pods = lambda _selector: [make_pod(phase="Pending")]

    with pytest.raises(SandboxNotRunningError, match="sbx-1"):
        gateway.get_ready_pod_ip("sbx-1")


def test_wait_for_pod_ready_retries_every_100ms(monkeypatch) -> None:
    gateway = object.__new__(KubernetesGateway)
    attempts = 0
    sleep_calls: list[float] = []

    def list_pods(_selector: str):
        nonlocal attempts
        attempts += 1
        return [] if attempts == 1 else [make_pod(ready=[True])]

    gateway.list_pods = list_pods
    monkeypatch.setattr(kubernetes_module.time, "sleep", sleep_calls.append)

    pod = gateway.wait_for_pod_ready("app=sbx-1")

    assert pod.status.pod_ip == "10.42.0.8"
    assert sleep_calls == [0.1]


def build_test_client(
    monkeypatch,
    handler,
    *,
    status: SandboxStatus = SandboxStatus.RUNNING,
    missing: bool = False,
    gateway_error: Exception | None = None,
):
    settings = Settings(
        auth=AuthConfig(bearer_token="test-secret"),
        envd=EnvdConfig(port=49983, connect_timeout_seconds=1.25, pod_ip_cache_ttl_seconds=5),
    )
    transport = RecordingTransport(handler)
    gateway = FakeGateway(error=gateway_error)
    proxy = EnvdProxyService(settings, gateway, transport=transport)
    transport.gateway = gateway
    container = SimpleNamespace(
        settings=settings,
        sandbox_service=FakeSandboxService(status=status, missing=missing),
        envd_proxy_service=proxy,
    )
    monkeypatch.setattr(main_module, "build_container", lambda: container)
    return TestClient(main_module.app), transport


def test_envd_options_requires_bearer_without_contacting_upstream(monkeypatch) -> None:
    upstream_calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal upstream_calls
        upstream_calls += 1
        return httpx.Response(204, stream=RecordingStream([]))

    client, _ = build_test_client(monkeypatch, handler)
    with client:
        response = client.options("/api/v1/sandboxes/sbx-1/envd/health")

    assert response.status_code == 401
    assert response.json() == {"success": False, "error": "Unauthorized"}
    assert upstream_calls == 0


def test_envd_cors_preflight_is_answered_without_contacting_upstream(monkeypatch) -> None:
    upstream_calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal upstream_calls
        upstream_calls += 1
        return httpx.Response(204, stream=RecordingStream([]))

    client, _ = build_test_client(monkeypatch, handler)
    with client:
        response = client.options(
            "/api/v1/sandboxes/sbx-1/envd/process.Process/Start",
            headers={
                "Origin": "https://dashboard.example.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://dashboard.example.com"
    assert upstream_calls == 0


def test_regular_api_options_remains_unauthenticated(monkeypatch) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("upstream must not be called")

    client, _ = build_test_client(monkeypatch, handler)
    with client:
        response = client.options("/api/v1/templates")

    assert response.status_code == 405


def test_proxy_rewrites_path_preserves_raw_query_and_filters_authorization(monkeypatch) -> None:
    upstream_requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        upstream_requests.append(request)
        return httpx.Response(200, stream=RecordingStream([b"ok"]))

    client, _ = build_test_client(monkeypatch, handler)
    with client:
        response = client.get(
            "/api/v1/sandboxes/sbx-1/envd/files?path=%2Fworkspace%2Fa.txt&value=a+b",
            headers={
                "Authorization": "Bearer test-secret",
                "Connect-Protocol-Version": "1",
                "Connection": "x-private",
                "X-Private": "remove-me",
            },
        )

    assert response.status_code == 200
    request = upstream_requests[0]
    assert request.url == httpx.URL(
        "http://10.42.0.8:49983/files?path=%2Fworkspace%2Fa.txt&value=a+b"
    )
    assert request.url.query == b"path=%2Fworkspace%2Fa.txt&value=a+b"
    assert "authorization" not in request.headers
    assert request.headers.get("connection") != "x-private"
    assert "x-private" not in request.headers
    assert request.headers["connect-protocol-version"] == "1"


def test_proxy_reuses_client_and_cached_pod_ip_for_sequential_requests(monkeypatch) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=RecordingStream([b"ok"]))

    client, transport = build_test_client(monkeypatch, handler)
    with client:
        headers = {"Authorization": "Bearer test-secret"}
        assert client.get("/api/v1/sandboxes/sbx-1/envd/health", headers=headers).content == b"ok"
        assert client.get("/api/v1/sandboxes/sbx-1/envd/health", headers=headers).content == b"ok"
        assert transport.gateway.calls == 1
        assert transport.close_calls == 0

    assert transport.close_calls == 1


def test_proxy_refreshes_expired_pod_ip_cache(monkeypatch) -> None:
    clock = iter([0.0, 6.0])
    monkeypatch.setattr(envd_proxy_module, "monotonic", lambda: next(clock))

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=RecordingStream([b"ok"]))

    client, transport = build_test_client(monkeypatch, handler)
    with client:
        headers = {"Authorization": "Bearer test-secret"}
        client.get("/api/v1/sandboxes/sbx-1/envd/health", headers=headers)
        client.get("/api/v1/sandboxes/sbx-1/envd/health", headers=headers)

    assert transport.gateway.calls == 2


def test_proxy_retries_safe_request_after_connection_failure_and_refreshes_pod_ip(monkeypatch) -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            raise httpx.ConnectError("stale pod", request=request)
        return httpx.Response(200, stream=RecordingStream([b"ok"]))

    settings = Settings(
        auth=AuthConfig(bearer_token="test-secret"),
        envd=EnvdConfig(port=49983, pod_ip_cache_ttl_seconds=5),
    )
    transport = RecordingTransport(handler)
    gateway = FakeGateway(pod_ips=["10.42.0.8", "10.42.0.9"])
    proxy = EnvdProxyService(settings, gateway, transport=transport)
    container = SimpleNamespace(
        settings=settings,
        sandbox_service=FakeSandboxService(),
        envd_proxy_service=proxy,
    )
    monkeypatch.setattr(main_module, "build_container", lambda: container)

    client = TestClient(main_module.app)
    with client:
        response = client.get(
            "/api/v1/sandboxes/sbx-1/envd/health",
            headers={"Authorization": "Bearer test-secret"},
        )

    assert response.status_code == 200
    assert response.content == b"ok"
    assert [str(request.url.host) for request in requests] == ["10.42.0.8", "10.42.0.9"]
    assert gateway.calls == 2


def test_proxy_does_not_retry_post_after_connection_failure(monkeypatch) -> None:
    upstream_calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal upstream_calls
        upstream_calls += 1
        raise httpx.ConnectError("connection refused", request=request)

    client, transport = build_test_client(monkeypatch, handler)
    with client:
        response = client.post(
            "/api/v1/sandboxes/sbx-1/envd/process.Process/Start",
            headers={"Authorization": "Bearer test-secret"},
            content=b"command",
        )

    assert response.status_code == 502
    assert upstream_calls == 1
    assert transport.gateway.calls == 1


def test_proxy_forwards_request_body_and_upstream_response(monkeypatch) -> None:
    request_bodies: list[bytes] = []
    stream = RecordingStream([b"first-", b"second"])

    async def handler(request: httpx.Request) -> httpx.Response:
        request_bodies.append(await request.aread())
        return httpx.Response(
            207,
            headers={
                "Content-Type": "application/connect+proto",
                "Connect-Protocol-Version": "1",
                "Connection": "x-private",
                "X-Private": "remove-me",
            },
            stream=stream,
        )

    client, transport = build_test_client(monkeypatch, handler)
    with client:
        response = client.post(
            "/api/v1/sandboxes/sbx-1/envd/process.Process/Start",
            headers={
                "Authorization": "Bearer test-secret",
                "Content-Type": "application/connect+proto",
            },
            content=b"request-payload",
        )

    assert request_bodies == [b"request-payload"]
    assert response.status_code == 207
    assert response.content == b"first-second"
    assert stream.yielded == [b"first-", b"second"]
    assert stream.closed is True
    assert transport.closed is True
    assert response.headers["content-type"] == "application/connect+proto"
    assert response.headers["connect-protocol-version"] == "1"
    assert "connection" not in response.headers
    assert "x-private" not in response.headers


@pytest.mark.parametrize(
    ("status", "missing", "gateway_error", "expected_status", "expected_error"),
    [
        (SandboxStatus.RUNNING, True, None, 404, "Sandbox not found"),
        (SandboxStatus.STOPPED, False, None, 409, "sandbox sbx-1 is not running"),
        (
            SandboxStatus.RUNNING,
            False,
            SandboxPodAddressUnavailableError("sandbox sbx-1 running Pod has no IP"),
            503,
            "sandbox sbx-1 running Pod has no IP",
        ),
    ],
)
def test_proxy_maps_sandbox_errors(
    monkeypatch,
    status,
    missing,
    gateway_error,
    expected_status,
    expected_error,
) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("upstream must not be called")

    client, _ = build_test_client(
        monkeypatch,
        handler,
        status=status,
        missing=missing,
        gateway_error=gateway_error,
    )
    with client:
        response = client.get(
            "/api/v1/sandboxes/sbx-1/envd/health",
            headers={"Authorization": "Bearer test-secret"},
        )

    assert response.status_code == expected_status
    assert response.json() == {"success": False, "error": expected_error}


def test_proxy_maps_upstream_connection_failure_without_closing_shared_client(monkeypatch) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client, transport = build_test_client(monkeypatch, handler)
    with client:
        response = client.get(
            "/api/v1/sandboxes/sbx-1/envd/health",
            headers={"Authorization": "Bearer test-secret"},
        )

    assert response.status_code == 502
    assert response.json() == {"success": False, "error": "envd upstream unavailable"}
    assert transport.closed is True


@pytest.mark.asyncio
async def test_proxy_background_closes_upstream_when_body_is_not_consumed() -> None:
    stream = RecordingStream([b"unused"])

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    transport = RecordingTransport(handler)
    settings = Settings(envd=EnvdConfig(port=49983))
    service = EnvdProxyService(settings, FakeGateway(), transport=transport)
    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/ignored",
            "raw_path": b"/ignored",
            "query_string": b"",
            "headers": [],
            "client": ("test", 1),
            "server": ("test", 80),
        }
    )

    response = await service.proxy("sbx-1", "health", request)
    assert response.background is not None
    await response.background()

    assert stream.closed is True
    await service.aclose()
    assert transport.closed is True
