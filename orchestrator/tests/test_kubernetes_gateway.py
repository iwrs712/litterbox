from __future__ import annotations

from types import SimpleNamespace

import orchestrator.infra.kubernetes as kubernetes_module
from orchestrator.infra.kubernetes import KubernetesGateway


class FakeCoreApi:
    def __init__(self, request_token: object) -> None:
        self.api_client = SimpleNamespace(request=request_token)

    def connect_get_namespaced_pod_exec(self, *args, **kwargs):
        raise AssertionError("stream() should intercept the exec API call")


def test_exec_stream_uses_dedicated_core_client(monkeypatch) -> None:
    gateway = object.__new__(KubernetesGateway)
    regular_request = object()
    gateway.core = FakeCoreApi(regular_request)
    gateway.namespace = "default"

    created_exec_apis: list[FakeCoreApi] = []

    def fake_build_core_api(cls) -> FakeCoreApi:
        api = FakeCoreApi(object())
        created_exec_apis.append(api)
        return api

    def fake_stream(api_method, pod_name, namespace, **kwargs):
        api_method.__self__.api_client.request = "websocket-request"
        return {
            "api": api_method.__self__,
            "pod_name": pod_name,
            "namespace": namespace,
            "kwargs": kwargs,
        }

    monkeypatch.setattr(KubernetesGateway, "_build_core_api", classmethod(fake_build_core_api))
    monkeypatch.setattr(kubernetes_module, "stream", fake_stream)

    pod = SimpleNamespace(
        metadata=SimpleNamespace(name="pod-1"),
        spec=SimpleNamespace(
            containers=[
                SimpleNamespace(name="main"),
                SimpleNamespace(name="sidecar"),
            ]
        ),
    )

    response = gateway._exec_stream(pod, command=["/bin/sh"], stdin=False, tty=False)

    assert len(created_exec_apis) == 1
    assert response["api"] is created_exec_apis[0]
    assert response["api"] is not gateway.core
    assert gateway.core.api_client.request is regular_request
    assert response["pod_name"] == "pod-1"
    assert response["namespace"] == "default"
    assert response["kwargs"]["container"] == "main"
