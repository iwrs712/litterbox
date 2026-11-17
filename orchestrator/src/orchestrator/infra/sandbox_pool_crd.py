from __future__ import annotations

from typing import Any

from kubernetes.client import ApiException

from orchestrator.config import Settings
from orchestrator.domain.models import Pool
from orchestrator.infra.kubernetes import KubernetesGateway
from orchestrator.infra.sandbox_crd import SandboxCRDGateway
from orchestrator.utils import utcnow

EXTENSIONS_GROUP = "extensions.agents.x-k8s.io"
API_VERSION = "v1beta1"


def _parse_timestamp(value: str | None):
    if not value:
        return None
    from datetime import datetime

    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class SandboxPoolRepository:
    """Pool metadata stored as ``SandboxWarmPool`` custom resources."""

    def __init__(
        self,
        gateway: KubernetesGateway,
        settings: Settings,
    ) -> None:
        self.gateway = gateway
        self.settings = settings
        self.namespace = gateway.namespace
        self.warmpools = SandboxCRDGateway(
            gateway,
            settings,
            group=EXTENSIONS_GROUP,
            version=API_VERSION,
            plural="sandboxwarmpools",
        )
        self.claims = SandboxCRDGateway(
            gateway,
            settings,
            group=EXTENSIONS_GROUP,
            version=API_VERSION,
            plural="sandboxclaims",
        )

    def get(self, template_id: str) -> Pool | None:
        try:
            cr = self.warmpools.get(template_id)
        except ApiException as exc:
            if exc.status == 404:
                return None
            raise
        if self._implicit(cr):
            return None
        return self._to_pool(cr)

    def get_status(self, template_id: str) -> dict[str, Any]:
        cr = self.warmpools.get(template_id)
        spec = cr.get("spec") or {}
        status = cr.get("status") or {}
        replicas = int(spec.get("replicas") or 0)
        ready = int(status.get("readyReplicas") or 0)
        allocated = 0
        terminating = 0
        for claim in self.claims.list(f"litterbox.io/pool={template_id}"):
            if (claim.get("metadata") or {}).get("deletionTimestamp"):
                terminating += 1
            else:
                allocated += 1
        return {
            "replicas": replicas,
            "ready": ready,
            "creating": max(replicas - ready, 0),
            "allocated": allocated,
            "failed": 0,
            "terminating": terminating,
        }

    def save(self, pool: Pool) -> Pool:
        body = self._build_body(pool)
        try:
            cr = self.warmpools.create(body)
        except ApiException as exc:
            if exc.status != 409:
                raise
            annotations = dict(body["metadata"]["annotations"])
            # A warm pool may have been created implicitly by a cold claim;
            # clear that marker so the pool becomes visible through the API.
            annotations["litterbox.io/implicit"] = None
            cr = self.warmpools.patch(
                pool.template_id,
                {
                    "metadata": {
                        "labels": body["metadata"]["labels"],
                        "annotations": annotations,
                    },
                    "spec": body["spec"],
                },
            )
        return self._to_pool(cr)

    def list(self) -> list[Pool]:
        result = self.warmpools.list("app=litterbox,component=pool")
        return [self._to_pool(item) for item in result if not self._implicit(item)]

    def delete(self, template_id: str) -> None:
        try:
            self.warmpools.delete(template_id)
        except ApiException as exc:
            if exc.status != 404:
                raise

    def request_reconcile(self, template_id: str) -> None:
        # The upstream warm pool controller reconciles continuously; there is
        # no separate reconcile trigger to publish.
        return None

    def _build_body(self, pool: Pool) -> dict[str, Any]:
        return {
            "apiVersion": f"{EXTENSIONS_GROUP}/{API_VERSION}",
            "kind": "SandboxWarmPool",
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
                    "litterbox.io/min-ready": str(pool.min_ready),
                    "litterbox.io/max-creating": str(pool.max_creating),
                },
            },
            "spec": {
                "replicas": pool.target_ready,
                "sandboxTemplateRef": {"name": pool.template_id},
            },
        }

    def _to_pool(self, cr: dict[str, Any]) -> Pool:
        metadata = cr.get("metadata") or {}
        spec = cr.get("spec") or {}
        annotations = metadata.get("annotations") or {}
        created_at = _parse_timestamp(metadata.get("creationTimestamp")) or utcnow()
        updated_at = _parse_timestamp(annotations.get("litterbox.io/updated-at")) or created_at
        target_ready = int(spec.get("replicas") or 0)
        return Pool(
            template_id=metadata.get("name", ""),
            enabled=target_ready > 0,
            min_ready=int(annotations.get("litterbox.io/min-ready") or 0),
            target_ready=target_ready,
            max_creating=int(annotations.get("litterbox.io/max-creating") or 5),
            sandbox_template={},
            created_at=created_at,
            updated_at=updated_at,
        )

    @staticmethod
    def _implicit(cr: dict[str, Any]) -> bool:
        annotations = (cr.get("metadata") or {}).get("annotations") or {}
        return annotations.get("litterbox.io/implicit") == "true"
