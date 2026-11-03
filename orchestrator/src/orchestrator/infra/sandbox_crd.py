from __future__ import annotations

import time
from typing import Any

from kubernetes import client
from kubernetes.client import ApiException

from orchestrator.config import Settings
from orchestrator.infra.kubernetes import KubernetesGateway


class SandboxCRDGateway:
    """Thin client for the ``litterbox.io/v1alpha1 Sandbox`` custom resource.

    The controller is the only component that creates Pods and PersistentVolume
    Claims. The orchestrator only writes desired state into the custom resource
    and reads the controller-written status back.
    """

    def __init__(self, gateway: KubernetesGateway, settings: Settings) -> None:
        self.gateway = gateway
        self.settings = settings
        self.namespace = gateway.namespace
        self.group = settings.sandbox.crd_group
        self.version = settings.sandbox.crd_version
        self.plural = settings.sandbox.crd_plural
        self.api = client.CustomObjectsApi(
            client.ApiClient(client.Configuration.get_default_copy())
        )

    def create(self, body: dict[str, Any]) -> dict[str, Any]:
        return self.api.create_namespaced_custom_object(
            self.group,
            self.version,
            self.namespace,
            self.plural,
            body,
        )

    def get(self, name: str) -> dict[str, Any]:
        return self.api.get_namespaced_custom_object(
            self.group,
            self.version,
            self.namespace,
            self.plural,
            name,
        )

    def list(self, label_selector: str = "") -> list[dict[str, Any]]:
        result = self.api.list_namespaced_custom_object(
            self.group,
            self.version,
            self.namespace,
            self.plural,
            label_selector=label_selector or None,
        )
        return result.get("items", [])

    def patch(self, name: str, body: dict[str, Any]) -> dict[str, Any]:
        return self.api.patch_namespaced_custom_object(
            self.group,
            self.version,
            self.namespace,
            self.plural,
            name,
            body,
        )

    def update_status(self, name: str, status: dict[str, Any]) -> dict[str, Any]:
        return self.api.patch_namespaced_custom_object_status(
            self.group,
            self.version,
            self.namespace,
            self.plural,
            name,
            {"status": status},
        )

    def delete(self, name: str) -> None:
        body = client.V1DeleteOptions(propagation_policy="Foreground")
        try:
            self.api.delete_namespaced_custom_object(
                self.group,
                self.version,
                self.namespace,
                self.plural,
                name,
                body=body,
            )
        except ApiException as exc:
            if exc.status != 404:
                raise

    def exists(self, name: str) -> bool:
        try:
            self.get(name)
        except ApiException as exc:
            if exc.status == 404:
                return False
            raise
        return True

    def wait_until_phase(
        self,
        name: str,
        phases: set[str],
        *,
        timeout_seconds: float = 5.0,
        interval_seconds: float = 0.1,
    ) -> dict[str, Any] | None:
        """Return the latest object once ``status.phase`` matches, else None.

        This is a control-plane convenience only. The data plane still waits
        for the Pod itself, so a slow status update never blocks a sandbox from
        becoming usable.
        """
        deadline = time.monotonic() + timeout_seconds
        latest: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            latest = self.get(name)
            phase = (latest.get("status") or {}).get("phase")
            if phase in phases:
                return latest
            time.sleep(interval_seconds)
        return latest
