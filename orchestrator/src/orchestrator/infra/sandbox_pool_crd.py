from __future__ import annotations

from typing import Any

from kubernetes import client
from kubernetes.client import ApiException

from orchestrator.config import Settings
from orchestrator.domain.models import Pool
from orchestrator.infra.kubernetes import KubernetesGateway
from orchestrator.utils import utcnow


def _parse_timestamp(value: str | None):
    if not value:
        return None
    from datetime import datetime

    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class SandboxPoolRepository:
    """ConfigMap-free pool metadata stored as SandboxPool custom resources."""

    plural = "sandboxpools"

    def __init__(
        self,
        gateway: KubernetesGateway,
        settings: Settings,
        api: client.CustomObjectsApi | None = None,
    ) -> None:
        self.gateway = gateway
        self.settings = settings
        self.namespace = gateway.namespace
        self.group = settings.sandbox.crd_group
        self.version = settings.sandbox.crd_version
        self.api = api or client.CustomObjectsApi(
            client.ApiClient(client.Configuration.get_default_copy())
        )

    def get(self, template_id: str) -> Pool | None:
        try:
            cr = self.api.get_namespaced_custom_object(
                self.group,
                self.version,
                self.namespace,
                self.plural,
                template_id,
            )
        except ApiException as exc:
            if exc.status == 404:
                return None
            raise
        return self._to_pool(cr)

    def get_status(self, template_id: str) -> dict[str, Any]:
        cr = self.api.get_namespaced_custom_object(
            self.group,
            self.version,
            self.namespace,
            self.plural,
            template_id,
        )
        return dict(cr.get("status") or {})

    def save(self, pool: Pool) -> Pool:
        body = self._build_body(pool)
        try:
            cr = self.api.create_namespaced_custom_object(
                self.group,
                self.version,
                self.namespace,
                self.plural,
                body,
            )
        except ApiException as exc:
            if exc.status != 409:
                raise
            cr = self.api.patch_namespaced_custom_object(
                self.group,
                self.version,
                self.namespace,
                self.plural,
                pool.template_id,
                {
                    "metadata": {
                        "labels": body["metadata"]["labels"],
                        "annotations": body["metadata"]["annotations"],
                    },
                    "spec": body["spec"],
                },
            )
        return self._to_pool(cr)

    def list(self) -> list[Pool]:
        result = self.api.list_namespaced_custom_object(
            self.group,
            self.version,
            self.namespace,
            self.plural,
            label_selector="app=litterbox,component=pool",
        )
        return [self._to_pool(item) for item in result.get("items", [])]

    def delete(self, template_id: str) -> None:
        try:
            self.api.delete_namespaced_custom_object(
                self.group,
                self.version,
                self.namespace,
                self.plural,
                template_id,
                body=client.V1DeleteOptions(propagation_policy="Foreground"),
            )
        except ApiException as exc:
            if exc.status != 404:
                raise

    def request_reconcile(self, template_id: str) -> None:
        try:
            self.api.patch_namespaced_custom_object(
                self.group,
                self.version,
                self.namespace,
                self.plural,
                template_id,
                {
                    "metadata": {
                        "annotations": {
                            "litterbox.io/reconcile-requested-at": utcnow().isoformat(),
                        }
                    }
                },
            )
        except ApiException as exc:
            if exc.status != 404:
                raise

    def _build_body(self, pool: Pool) -> dict[str, Any]:
        return {
            "apiVersion": f"{self.group}/{self.version}",
            "kind": "SandboxPool",
            "metadata": {
                "name": pool.template_id,
                "namespace": self.namespace,
                "labels": {
                    "app": "litterbox",
                    "component": "pool",
                    "litterbox.io/template-id": pool.template_id,
                },
                "annotations": {
                    "litterbox.io/updated-at": pool.updated_at.isoformat(),
                },
            },
            "spec": {
                "templateID": pool.template_id,
                "targetReady": pool.target_ready,
                "minReady": pool.min_ready,
                "maxCreating": pool.max_creating,
                "sandboxTemplate": pool.sandbox_template,
            },
        }

    def _to_pool(self, cr: dict[str, Any]) -> Pool:
        metadata = cr.get("metadata") or {}
        spec = cr.get("spec") or {}
        annotations = metadata.get("annotations") or {}
        created_at = _parse_timestamp(metadata.get("creationTimestamp")) or utcnow()
        updated_at = _parse_timestamp(annotations.get("litterbox.io/updated-at")) or created_at
        target_ready = int(spec.get("targetReady") or 0)
        return Pool(
            template_id=metadata.get("name", ""),
            enabled=target_ready > 0,
            min_ready=int(spec.get("minReady") or 0),
            target_ready=target_ready,
            max_creating=int(spec.get("maxCreating") or 5),
            sandbox_template=dict(spec.get("sandboxTemplate") or {}),
            created_at=created_at,
            updated_at=updated_at,
        )
