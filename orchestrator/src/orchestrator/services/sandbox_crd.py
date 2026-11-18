from __future__ import annotations

from datetime import datetime, timedelta
import shlex
import time
from typing import Any

from kubernetes.client import ApiException

from orchestrator.config import Settings
from orchestrator.domain.models import (
    PoolState,
    Sandbox,
    SandboxStatus,
    Template,
    WorkspaceConfig,
)
from orchestrator.infra.kubernetes import KubernetesGateway
from orchestrator.infra.sandbox_crd import SandboxCRDGateway
from orchestrator.utils import is_valid_label_part, parse_env_list, utcnow

SANDBOX_GROUP = "agents.x-k8s.io"
EXTENSIONS_GROUP = "extensions.agents.x-k8s.io"
API_VERSION = "v1beta1"


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _iso(value: datetime) -> str:
    return value.astimezone().isoformat().replace("+00:00", "Z")


class SandboxCRDService:
    """Translates the orchestrator domain model to agent-sandbox resources.

    Public sandbox ids are ``SandboxClaim`` names. A claim always points at a
    ``SandboxWarmPool``; templates without a configured pool use an implicit
    zero-replica pool so the claim can still be cold-started from its
    ``SandboxTemplate``.
    """

    def __init__(
        self,
        settings: Settings,
        gateway: KubernetesGateway,
        crd_gateway: SandboxCRDGateway | None = None,
    ) -> None:
        self.settings = settings
        self.gateway = gateway
        self.namespace = gateway.namespace
        self.sandboxes = SandboxCRDGateway(
            gateway, settings, group=SANDBOX_GROUP, version=API_VERSION, plural="sandboxes"
        )
        self.claims = SandboxCRDGateway(
            gateway, settings, group=EXTENSIONS_GROUP, version=API_VERSION, plural="sandboxclaims"
        )
        self.templates = SandboxCRDGateway(
            gateway, settings, group=EXTENSIONS_GROUP, version=API_VERSION, plural="sandboxtemplates"
        )
        self.warmpools = SandboxCRDGateway(
            gateway, settings, group=EXTENSIONS_GROUP, version=API_VERSION, plural="sandboxwarmpools"
        )

    # ------------------------------------------------------------------
    # Templates and pools
    # ------------------------------------------------------------------

    def ensure_template(self, template: Template, workspace: WorkspaceConfig) -> None:
        body = {
            "apiVersion": f"{EXTENSIONS_GROUP}/{API_VERSION}",
            "kind": "SandboxTemplate",
            "metadata": {
                "name": template.id,
                "namespace": self.namespace,
                "labels": {
                    "app": "litterbox",
                    "component": "template",
                    "litterbox.io/template-id": template.id,
                },
            },
            "spec": {
                "envVarsInjectionPolicy": "Allowed",
                "failedPodPolicy": "Recreate",
                "networkPolicyManagement": "Unmanaged",
                "service": False,
                "podTemplate": self.build_pod_template(template, workspace),
                **self.build_volume_claim_templates(workspace),
            },
        }
        try:
            self.templates.get(template.id)
        except ApiException as exc:
            if exc.status != 404:
                raise
            self.templates.create(body)
            return
        self.templates.patch(template.id, {"spec": body["spec"]})

    def ensure_warmpool(self, template_id: str) -> None:
        try:
            self.warmpools.get(template_id)
            return
        except ApiException as exc:
            if exc.status != 404:
                raise
        self.warmpools.create(
            {
                "apiVersion": f"{EXTENSIONS_GROUP}/{API_VERSION}",
                "kind": "SandboxWarmPool",
                "metadata": {
                    "name": template_id,
                    "namespace": self.namespace,
                    "labels": {
                        "app": "litterbox",
                        "component": "pool",
                        "litterbox.io/template-id": template_id,
                    },
                    "annotations": {
                        "litterbox.io/implicit": "true",
                        "litterbox.io/min-ready": "0",
                        "litterbox.io/max-creating": "5",
                    },
                },
                "spec": {
                    "replicas": 0,
                    "sandboxTemplateRef": {"name": template_id},
                },
            }
        )

    # ------------------------------------------------------------------
    # Sandbox lifecycle
    # ------------------------------------------------------------------

    def create(
        self,
        *,
        sandbox_id: str,
        template: Template,
        metadata: dict[str, str],
        name: str,
        env: list[str] | None,
        pool_state: str,
        ttl_seconds: int | None,
        workspace: WorkspaceConfig,
    ) -> Sandbox:
        self.ensure_template(template, workspace)
        self.ensure_warmpool(template.id)
        body = self.build_claim(
            sandbox_id=sandbox_id,
            template=template,
            metadata=metadata,
            name=name,
            env=env,
            pool_state=pool_state,
            ttl_seconds=ttl_seconds,
            workspace=workspace,
        )
        return self.to_sandbox(self.claims.create(body), sandbox=None)

    def build_claim(
        self,
        *,
        sandbox_id: str,
        template: Template,
        metadata: dict[str, str],
        name: str,
        env: list[str] | None,
        pool_state: str,
        ttl_seconds: int | None,
        workspace: WorkspaceConfig,
    ) -> dict[str, Any]:
        effective_ttl = ttl_seconds if ttl_seconds is not None else (template.ttl_seconds or 0)
        if effective_ttl < 0:
            effective_ttl = 0
        anchor = utcnow() if effective_ttl > 0 else None

        labels = {
            "component": "sandbox",
            "litterbox.io/template-id": template.id,
            "litterbox.io/sandbox-id": sandbox_id,
        }
        annotations = {
            "litterbox.io/created-at": utcnow().isoformat(),
            "litterbox.io/workspace-config": workspace.model_dump_json(),
            "litterbox.io/ttl-seconds": str(effective_ttl),
        }
        if anchor is not None:
            annotations["litterbox.io/ttl-anchor"] = anchor.isoformat()
        if self.settings.envd.enabled:
            annotations["litterbox.io/envd-version"] = self.settings.envd.version
        if name:
            annotations["litterbox.io/allocated-name"] = name
        if pool_state != PoolState.NONE:
            labels["litterbox.io/pool-state"] = pool_state
            labels["litterbox.io/pool"] = template.id

        pod_labels = {
            "litterbox.io/sandbox-id": sandbox_id,
            "litterbox.io/template-id": template.id,
        }
        for key, value in metadata.items():
            label_key = f"litterbox.io/user-{key}"
            annotation_key = f"litterbox.io/user-metadata-{key}"
            if is_valid_label_part(key) and is_valid_label_part(value):
                labels[label_key] = value
                pod_labels[label_key] = value
                annotations.pop(annotation_key, None)
            else:
                annotations[annotation_key] = value
                labels.pop(label_key, None)

        spec: dict[str, Any] = {
            "warmPoolRef": {"name": template.id},
            "additionalPodMetadata": {"labels": pod_labels},
        }
        claim_env = [
            {"containerName": "main", "name": key, "value": value}
            for key, value in parse_env_list(env or [])
        ]
        if claim_env:
            spec["env"] = claim_env

        return {
            "apiVersion": f"{EXTENSIONS_GROUP}/{API_VERSION}",
            "kind": "SandboxClaim",
            "metadata": {
                "name": sandbox_id,
                "namespace": self.namespace,
                "labels": labels,
                "annotations": annotations,
            },
            "spec": spec,
        }

    def patch_metadata(
        self,
        sandbox_id: str,
        *,
        labels: dict[str, str] | None = None,
        annotations: dict[str, str] | None = None,
        annotations_to_remove: tuple[str, ...] = (),
    ) -> None:
        metadata: dict[str, Any] = {}
        if labels is not None:
            metadata["labels"] = labels
        if annotations is not None:
            annotations = dict(annotations)
            annotations["litterbox.io/updated-at"] = utcnow().isoformat()
            annotation_patch: dict[str, str | None] = dict(annotations)
            for key in annotations_to_remove:
                annotation_patch[key] = None
            metadata["annotations"] = annotation_patch
        if metadata:
            self.claims.patch(sandbox_id, {"metadata": metadata})

    def set_ttl(self, sandbox_id: str, ttl_seconds: int) -> None:
        ttl_seconds = max(int(ttl_seconds), 0)
        anchor = utcnow()
        annotations = {
            "litterbox.io/ttl-seconds": str(ttl_seconds),
            "litterbox.io/ttl-anchor": anchor.isoformat() if ttl_seconds > 0 else None,
            "litterbox.io/updated-at": utcnow().isoformat(),
        }
        self.claims.patch(
            sandbox_id,
            {"metadata": {"annotations": annotations}},
        )

    def renew_ttl(self, sandbox_id: str, *, ttl_seconds: int, current_ttl: int) -> None:
        effective_ttl = ttl_seconds or current_ttl
        anchor = utcnow() + timedelta(seconds=effective_ttl - current_ttl)
        self.claims.patch(
            sandbox_id,
            {
                "metadata": {
                    "annotations": {
                        "litterbox.io/ttl-anchor": anchor.isoformat(),
                        "litterbox.io/updated-at": utcnow().isoformat(),
                    }
                }
            },
        )

    def suspend(self, sandbox_id: str, *, ttl_expired: bool = False) -> None:
        sandbox_name = self._sandbox_name(sandbox_id)
        if sandbox_name:
            self.sandboxes.patch(sandbox_name, {"spec": {"operatingMode": "Suspended"}})
        annotations: dict[str, Any] = {"litterbox.io/updated-at": utcnow().isoformat()}
        if ttl_expired:
            annotations["litterbox.io/ttl-suspended-at"] = utcnow().isoformat()
        self.claims.patch(sandbox_id, {"metadata": {"annotations": annotations}})

    def resume(self, sandbox_id: str, *, ttl_seconds: int) -> None:
        sandbox_name = self._sandbox_name(sandbox_id)
        if sandbox_name:
            self.sandboxes.patch(sandbox_name, {"spec": {"operatingMode": "Running"}})
        annotations: dict[str, Any] = {
            "litterbox.io/updated-at": utcnow().isoformat(),
            "litterbox.io/ttl-suspended-at": None,
        }
        if ttl_seconds > 0:
            annotations["litterbox.io/ttl-anchor"] = utcnow().isoformat()
        self.claims.patch(sandbox_id, {"metadata": {"annotations": annotations}})

    def lock(self, sandbox_id: str) -> None:
        now = utcnow().isoformat()
        self.claims.patch(
            sandbox_id,
            {
                "metadata": {
                    "annotations": {
                        "litterbox.io/resume-locked": "true",
                        "litterbox.io/resume-locked-at": now,
                        "litterbox.io/updated-at": now,
                    }
                }
            },
        )

    def unlock(self, sandbox_id: str) -> None:
        self.claims.patch(
            sandbox_id,
            {
                "metadata": {
                    "annotations": {
                        "litterbox.io/resume-locked": None,
                        "litterbox.io/resume-locked-at": None,
                        "litterbox.io/updated-at": utcnow().isoformat(),
                    }
                }
            },
        )

    def delete(self, sandbox_id: str) -> None:
        self.claims.delete(sandbox_id)

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_cr(self, sandbox_id: str) -> dict[str, Any]:
        claim = self.claims.get(sandbox_id)
        sandbox = self._sandbox_for_claim(claim)
        return self._view(claim, sandbox)

    def get(self, sandbox_id: str) -> Sandbox:
        claim = self.claims.get(sandbox_id)
        return self.to_sandbox(claim, self._sandbox_for_claim(claim))

    def list(self, label_selector: str = "") -> list[Sandbox]:
        claims = self.claims.list(label_selector)
        sandboxes = self._sandboxes_by_claim()
        return [
            self.to_sandbox(claim, sandboxes.get((claim.get("metadata") or {}).get("name", "")))
            for claim in claims
        ]

    def wait_until_running(self, sandbox_id: str, timeout_seconds: float = 10.0) -> None:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            phase = (self.get_cr(sandbox_id).get("status") or {}).get("phase")
            if phase == "Running":
                return
            time.sleep(0.2)

    def wait_until_paused(self, sandbox_id: str, timeout_seconds: float = 10.0) -> None:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            sandbox = self._sandbox_for_claim(self.claims.get(sandbox_id))
            if sandbox is not None:
                conditions = {c.get("type"): c for c in (sandbox.get("status") or {}).get("conditions", [])}
                if (conditions.get("Suspended") or {}).get("status") == "True":
                    return
            time.sleep(0.2)

    # ------------------------------------------------------------------
    # Translation helpers
    # ------------------------------------------------------------------

    def build_volume_claim_templates(self, workspace: WorkspaceConfig) -> dict[str, Any]:
        if not workspace.enabled:
            return {}
        claim_spec: dict[str, Any] = {
            "accessModes": ["ReadWriteOnce"],
            "resources": {"requests": {"storage": workspace.size}},
        }
        if workspace.storage_class:
            claim_spec["storageClassName"] = workspace.storage_class
        return {
            "volumeClaimTemplates": [
                {"metadata": {"name": "workspace"}, "spec": claim_spec}
            ]
        }

    def build_pod_template(self, template: Template, workspace: WorkspaceConfig) -> dict[str, Any]:
        volumes: list[dict[str, Any]] = []
        volume_mounts: list[dict[str, Any]] = []
        ports: list[dict[str, Any]] = []

        if workspace.enabled:
            # The Sandbox controller injects a PVC-backed volume named after the
            # volumeClaimTemplate; only the mount belongs in the pod template.
            volume_mounts.append({"name": "workspace", "mountPath": workspace.mount_path})

        envd_enabled = self.settings.envd.enabled
        if envd_enabled:
            volumes.append(
                {
                    "name": "envd",
                    "hostPath": {"path": self.settings.envd.host_binary_path, "type": "File"},
                }
            )
            volume_mounts.append(
                {
                    "name": "envd",
                    "mountPath": self.settings.envd.container_binary_path,
                    "readOnly": True,
                }
            )
            ports.append({"name": "envd", "containerPort": self.settings.envd.port})

        for index, mount in enumerate(template.host_path_mounts):
            name = f"host-mount-{index}"
            volumes.append(
                {"name": name, "hostPath": {"path": mount.host_path, "type": "DirectoryOrCreate"}}
            )
            volume_mounts.append(
                {"name": name, "mountPath": mount.container_path, "readOnly": mount.read_only}
            )

        post_start: list[str] | None = None
        if envd_enabled:
            if template.lifecycle is not None and template.lifecycle.post_start is not None:
                raise ValueError("template postStart conflicts with envd injection")
            post_start = [
                self.settings.envd.container_binary_path,
                "daemon",
                "--host",
                "0.0.0.0",
                "--port",
                str(self.settings.envd.port),
                "--filesystem-root",
                "/",
            ]
        elif template.lifecycle is not None and template.lifecycle.post_start is not None:
            post_start = list(template.lifecycle.post_start.exec.command)

        pre_stop: list[str] | None = None
        termination_grace_period_seconds = 10
        if template.lifecycle is not None and template.lifecycle.pre_stop is not None:
            pre_stop = list(template.lifecycle.pre_stop.exec.command)
            termination_grace_period_seconds = (
                template.lifecycle.pre_stop.termination_grace_period_seconds or 10
            )

        runtime_class_name = self.settings.kubernetes.runtime_class or ""
        if runtime_class_name not in self.gateway.available_runtime_classes:
            runtime_class_name = ""

        image_pull_secret = self.settings.kubernetes.image_pull_secret or ""
        if image_pull_secret and not self.gateway.secret_exists(image_pull_secret):
            image_pull_secret = ""

        lifecycle: dict[str, Any] | None = None
        if post_start or pre_stop:
            lifecycle = {}
            if post_start:
                lifecycle["postStart"] = {"exec": {"command": post_start}}
            if pre_stop:
                lifecycle["preStop"] = {"exec": {"command": pre_stop}}

        container: dict[str, Any] = {
            "name": "main",
            "image": template.image,
            "command": shlex.split(template.command) if template.command else [],
            "env": [{"name": key, "value": value} for key, value in parse_env_list(template.env)],
            "ports": ports,
            "resources": {
                "limits": {
                    "cpu": f"{template.cpu_millicores}m",
                    "memory": f"{template.memory_mb}Mi",
                    "ephemeral-storage": self.settings.sandbox.ephemeral_storage_limit,
                },
                "requests": {
                    "cpu": f"{template.cpu_request or template.cpu_millicores}m",
                    "memory": f"{template.memory_request or template.memory_mb}Mi",
                    "ephemeral-storage": self.settings.sandbox.ephemeral_storage_request,
                },
            },
            "securityContext": {"appArmorProfile": {"type": "Unconfined"}},
            "stdin": True,
            "tty": True,
            "volumeMounts": volume_mounts,
        }
        if lifecycle is not None:
            container["lifecycle"] = lifecycle

        spec: dict[str, Any] = {
            "automountServiceAccountToken": False,
            "restartPolicy": "Always",
            "terminationGracePeriodSeconds": termination_grace_period_seconds,
            "containers": [container],
            "volumes": volumes,
        }
        if runtime_class_name:
            spec["runtimeClassName"] = runtime_class_name
        if image_pull_secret:
            spec["imagePullSecrets"] = [{"name": image_pull_secret}]
        if envd_enabled:
            spec["nodeSelector"] = {"litterbox.io/envd-version": self.settings.envd.version}

        return {
            "metadata": {
                "labels": {
                    "component": "sandbox",
                    "litterbox.io/template-id": template.id,
                }
            },
            "spec": spec,
        }

    def sandbox_name(self, sandbox_id: str) -> str:
        return self._sandbox_name(sandbox_id)

    def _sandbox_name(self, sandbox_id: str) -> str:
        claim = self.claims.get(sandbox_id)
        return ((claim.get("status") or {}).get("sandbox") or {}).get("name", "")

    def _sandbox_for_claim(self, claim: dict[str, Any]) -> dict[str, Any] | None:
        name = ((claim.get("status") or {}).get("sandbox") or {}).get("name", "")
        if not name:
            return None
        try:
            return self.sandboxes.get(name)
        except ApiException as exc:
            if exc.status == 404:
                return None
            raise

    def _sandboxes_by_claim(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for sandbox in self.sandboxes.list():
            for ref in (sandbox.get("metadata") or {}).get("ownerReferences") or []:
                if ref.get("kind") == "SandboxClaim":
                    result[ref.get("name", "")] = sandbox
        return result

    def _view(self, claim: dict[str, Any], sandbox: dict[str, Any] | None) -> dict[str, Any]:
        metadata = dict(claim.get("metadata") or {})
        annotations = dict(metadata.get("annotations") or {})
        spec = dict(claim.get("spec") or {})
        status: dict[str, Any] = {}
        phase = "Pending"
        ttl_seconds = int(annotations.get("litterbox.io/ttl-seconds") or 0)
        anchor = _parse_timestamp(annotations.get("litterbox.io/ttl-anchor"))
        if ttl_seconds > 0 and anchor is not None:
            status["expiresAt"] = _iso(anchor + timedelta(seconds=ttl_seconds))
        if sandbox is not None:
            conditions = {
                c.get("type"): c for c in (sandbox.get("status") or {}).get("conditions", [])
            }
            if (conditions.get("Suspended") or {}).get("status") == "True":
                phase = "Paused"
            elif (conditions.get("Ready") or {}).get("status") == "True":
                phase = "Running"
            status["podIPs"] = list((sandbox.get("status") or {}).get("podIPs") or [])
        else:
            claim_conditions = {
                c.get("type"): c for c in (claim.get("status") or {}).get("conditions", [])
            }
            reason = (claim_conditions.get("Ready") or {}).get("reason")
            if reason in {"InvalidMetadata", "Failed"}:
                phase = "Failed"
        status["phase"] = phase
        return {
            "metadata": metadata,
            "spec": {
                "ttlSeconds": ttl_seconds,
                "ttlAnchor": annotations.get("litterbox.io/ttl-anchor"),
                "state": "Paused" if phase == "Paused" else "Running",
                "warmPoolRef": spec.get("warmPoolRef"),
            },
            "status": status,
        }

    def to_sandbox(self, claim: dict[str, Any], sandbox: dict[str, Any] | None) -> Sandbox:
        view = self._view(claim, sandbox)
        metadata = view["metadata"]
        labels = metadata.get("labels") or {}
        annotations = metadata.get("annotations") or {}
        status = view["status"]

        created_at = _parse_timestamp(metadata.get("creationTimestamp")) or utcnow()
        updated_at = _parse_timestamp(annotations.get("litterbox.io/updated-at")) or created_at
        ttl_seconds = int(annotations.get("litterbox.io/ttl-seconds") or 0)
        expires_at = None
        if ttl_seconds > 0:
            anchor = _parse_timestamp(annotations.get("litterbox.io/ttl-anchor"))
            if anchor is not None:
                expires_at = anchor + timedelta(seconds=ttl_seconds)
            else:
                expires_at = _parse_timestamp(status.get("expiresAt"))

        workspace = None
        raw_workspace = annotations.get("litterbox.io/workspace-config")
        if raw_workspace:
            try:
                workspace = WorkspaceConfig.model_validate_json(raw_workspace)
            except ValueError:
                pass

        terminating = metadata.get("deletionTimestamp") is not None
        if terminating:
            sandbox_status = SandboxStatus.STOPPED
        else:
            phase = str(status.get("phase") or "Pending")
            sandbox_status = {
                "Running": SandboxStatus.RUNNING,
                "Paused": SandboxStatus.STOPPED,
                "Failed": SandboxStatus.EXITED,
                "Succeeded": SandboxStatus.EXITED,
                "Pending": SandboxStatus.CREATED,
            }.get(phase, SandboxStatus.UNKNOWN)

        return Sandbox(
            id=metadata.get("name", ""),
            name=annotations.get("litterbox.io/allocated-name", metadata.get("name", "")),
            template_id=labels.get("litterbox.io/template-id", ""),
            status=sandbox_status,
            terminating=terminating,
            pool_state=labels.get("litterbox.io/pool-state", PoolState.NONE),
            metadata=extract_metadata(labels, annotations),
            allocated_at=_parse_timestamp(annotations.get("litterbox.io/allocated-at")),
            created_at=created_at,
            updated_at=updated_at,
            ttl_seconds=ttl_seconds,
            expires_at=expires_at,
            locked=annotations.get("litterbox.io/resume-locked") == "true",
            workspace=workspace,
        )


def extract_metadata(labels: dict[str, str], annotations: dict[str, str]) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for key, value in labels.items():
        if key.startswith("litterbox.io/user-"):
            metadata[key.removeprefix("litterbox.io/user-")] = value
    for key, value in annotations.items():
        if key.startswith("litterbox.io/user-metadata-"):
            metadata[key.removeprefix("litterbox.io/user-metadata-")] = value
    return metadata
