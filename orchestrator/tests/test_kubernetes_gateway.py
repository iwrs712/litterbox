from __future__ import annotations

from types import SimpleNamespace

from orchestrator.infra.kubernetes import KubernetesGateway


class FakeCoreApi:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.items = [
            SimpleNamespace(
                metadata=SimpleNamespace(name="pod-1", deletion_timestamp=None),
                status=SimpleNamespace(
                    phase="Running",
                    pod_ip="10.0.0.7",
                    container_statuses=[SimpleNamespace(ready=True)],
                ),
            )
        ]

    def list_namespaced_pod(self, namespace: str, label_selector: str):
        self.calls.append((namespace, label_selector))
        return SimpleNamespace(items=self.items)


def build_gateway() -> tuple[KubernetesGateway, FakeCoreApi]:
    gateway = object.__new__(KubernetesGateway)
    gateway.namespace = "default"
    gateway.core = FakeCoreApi()
    return gateway, gateway.core


def test_list_pods_uses_label_selector() -> None:
    gateway, core = build_gateway()

    pods = gateway.list_pods("app=sbx,component=sandbox")

    assert [pod.metadata.name for pod in pods] == ["pod-1"]
    assert core.calls == [("default", "app=sbx,component=sandbox")]


def test_get_ready_pod_ip_returns_running_pod_address() -> None:
    gateway, _ = build_gateway()

    assert gateway.get_ready_pod_ip("sbx") == "10.0.0.7"
