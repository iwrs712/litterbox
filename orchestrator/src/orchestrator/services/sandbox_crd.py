from __future__ import annotations

from datetime import datetime, timedelta
import shlex
from typing import Any

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


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


class SandboxCRDService:
    """Translates the orchestrator domain model to Sandbox custom resources."""

    def __init__(
        self,
        settings: Settings,
        gateway: KubernetesGateway,
        crd_gateway: SandboxCRDGateway,
    ) -> None:
        self.settings = settings
        self.gateway = gateway
        self.crd = crd_gateway

    # ------------------------------------------------------------------
    # Writes
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
        body = self.build_object(
            sandbox_id=sandbox_id,
            template=template,
            metadata=metadata,
            name=name,
            env=env,
            pool_state=pool_state,
            ttl_seconds=ttl_seconds,
            workspace=workspace,
        )
        return self.to_sandbox(self.crd.create(body))

    def build_object(
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
        labels = {
            "app": sandbox_id,
            "component": "sandbox",
            "litterbox.io/template-id": template.id,
            "litterbox.io/sandbox-id": sandbox_id,
            "litterbox.io/cpu-millicores": str(template.cpu_millicores),
            "litterbox.io/memory-mb": str(template.memory_mb),
        }
        if pool_state != PoolState.NONE:
            labels["litterbox.io/pool-managed"] = "true"
            labels["litterbox.io/pool-state"] = pool_state

        annotations = {
            "litterbox.io/template-id": template.id,
            "litterbox.io/created-at": utcnow().isoformat(),
            "litterbox.io/workspace-config": workspace.model_dump_json(),
        }
        if name:
            annotations["litterbox.io/allocated-name"] = name
        for key, value in metadata.items():
            if is_valid_label_part(key) and is_valid_label_part(value):
                labels[f"litterbox.io/user-{key}"] = value
            else:
                annotations[f"litterbox.io/user-metadata-{key}"] = value

        effective_ttl = ttl_seconds if ttl_seconds is not None else (template.ttl_seconds or 0)
        if effective_ttl < 0:
            effective_ttl = 0

        merged_env_map: dict[str, str] = {}
        for key, value in parse_env_list([*template.env, *(env or [])]):
            merged_env_map[key] = value
        container_env = [
            {"name": key, "value": value} for key, value in merged_env_map.items()
        ]

        volumes: list[dict[str, Any]] = []
        volume_mounts: list[dict[str, Any]] = []
        container_ports: list[dict[str, Any]] = []
        if workspace.enabled:
            volumes.append(
                {
                    "name": "workspace",
                    "persistentVolumeClaim": {
                        "claimName": workspace_claim_name(sandbox_id),
                    },
                }
            )
            volume_mounts.append(
                {"name": "workspace", "mountPath": workspace.mount_path}
            )

        envd_enabled = self.settings.envd.enabled
        if envd_enabled:
            annotations["litterbox.io/envd-version"] = self.settings.envd.version
            volumes.append(
                {
                    "name": "envd",
                    "hostPath": {
                        "path": self.settings.envd.host_binary_path,
                        "type": "File",
                    },
                }
            )
            volume_mounts.append(
                {
                    "name": "envd",
                    "mountPath": self.settings.envd.container_binary_path,
                    "readOnly": True,
                }
            )
            container_ports.append(
                {"name": "envd", "containerPort": self.settings.envd.port}
            )

        for index, mount in enumerate(template.host_path_mounts):
            volume_name = f"host-mount-{index}"
            volumes.append(
                {
                    "name": volume_name,
                    "hostPath": {"path": mount.host_path, "type": "DirectoryOrCreate"},
                }
            )
            volume_mounts.append(
                {
                    "name": volume_name,
                    "mountPath": mount.container_path,
                    "readOnly": mount.read_only,
                }
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
        termination_grace_period_seconds = 0
        if template.lifecycle is not None and template.lifecycle.pre_stop is not None:
            pre_stop = list(template.lifecycle.pre_stop.exec.command)
            termination_grace_period_seconds = (
                template.lifecycle.pre_stop.termination_grace_period_seconds or 0
            )

        runtime_class_name = self.settings.kubernetes.runtime_class
        if runtime_class_name not in self.gateway.available_runtime_classes:
            runtime_class_name = ""

        image_pull_secret = self.settings.kubernetes.image_pull_secret or ""
        if image_pull_secret and not self.gateway.secret_exists(image_pull_secret):
            image_pull_secret = ""

        lifecycle: dict[str, Any] = {
            "terminationGracePeriodSeconds": termination_grace_period_seconds,
        }
        if post_start is not None:
            lifecycle["postStart"] = post_start
        if pre_stop is not None:
            lifecycle["preStop"] = pre_stop

        spec: dict[str, Any] = {
            "templateID": template.id,
            "image": template.image,
            "command": shlex.split(template.command) if template.command else [],
            "env": container_env,
            "resources": {
                "limits": {
                    "cpu": f"{template.cpu_millicores}m",
                    "memory": f"{template.memory_mb}Mi",
                },
                "requests": {
                    "cpu": f"{template.cpu_request or template.cpu_millicores}m",
                    "memory": f"{template.memory_request or template.memory_mb}Mi",
                },
            },
            "runtimeClassName": runtime_class_name,
            "imagePullSecret": image_pull_secret,
            "nodeSelector": (
                {"litterbox.io/envd-version": self.settings.envd.version}
                if envd_enabled
                else {}
            ),
            "hostPathMounts": [
                {
                    "hostPath": mount.host_path,
                    "containerPath": mount.container_path,
                    "readOnly": mount.read_only,
                }
                for mount in template.host_path_mounts
            ],
            "workspace": {
                "enabled": workspace.enabled,
                "mountPath": workspace.mount_path,
                "size": workspace.size,
                "storageClassName": workspace.storage_class or "",
                "claimName": workspace_claim_name(sandbox_id),
            },
            "envd": {
                "enabled": envd_enabled,
                "hostBinaryPath": self.settings.envd.host_binary_path,
                "containerBinaryPath": self.settings.envd.container_binary_path,
                "port": self.settings.envd.port,
            },
            "lifecycle": lifecycle,
            "state": "Running",
            "ttlSeconds": effective_ttl,
            "appArmorUnconfined": True,
            "stdin": True,
            "tty": True,
        }
        if effective_ttl > 0:
            spec["ttlAnchor"] = utcnow().isoformat()

        return {
            "apiVersion": f"{self.crd.group}/{self.crd.version}",
            "kind": "Sandbox",
            "metadata": {
                "name": sandbox_id,
                "namespace": self.crd.namespace,
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
            annotations["litterbox.io/updated-at"] = utcnow().isoformat()
            annotation_patch: dict[str, str | None] = dict(annotations)
            for key in annotations_to_remove:
                annotation_patch[key] = None
            metadata["annotations"] = annotation_patch
        if metadata:
            self.crd.patch(sandbox_id, {"metadata": metadata})

    def mark_allocated(
        self,
        sandbox_id: str,
        *,
        labels: dict[str, str],
        annotations: dict[str, str],
        ttl_seconds: int,
    ) -> None:
        annotations["litterbox.io/updated-at"] = utcnow().isoformat()
        self.crd.patch(
            sandbox_id,
            {
                "metadata": {"labels": labels, "annotations": annotations},
                "spec": {
                    "ttlSeconds": ttl_seconds,
                    "ttlAnchor": utcnow().isoformat() if ttl_seconds > 0 else None,
                },
            },
        )

    def set_ttl(self, sandbox_id: str, ttl_seconds: int) -> None:
        self.crd.patch(
            sandbox_id,
            {
                "metadata": {"annotations": {"litterbox.io/updated-at": utcnow().isoformat()}},
                "spec": {
                    "ttlSeconds": ttl_seconds,
                    "ttlAnchor": utcnow().isoformat() if ttl_seconds > 0 else None,
                },
            },
        )

    def renew_ttl(self, sandbox_id: str, *, ttl_seconds: int, current_ttl: int) -> None:
        # The configured TTL stays unchanged; only the next expiry moves. Keep
        # the anchor consistent with ``expiresAt = anchor + current_ttl``.
        effective_ttl = ttl_seconds or current_ttl
        anchor = utcnow() + timedelta(seconds=effective_ttl - current_ttl)
        self.crd.patch(
            sandbox_id,
            {
                "metadata": {"annotations": {"litterbox.io/updated-at": utcnow().isoformat()}},
                "spec": {"ttlAnchor": anchor.isoformat()},
            },
        )

    def suspend(self, sandbox_id: str, *, ttl_expired: bool = False) -> None:
        metadata: dict[str, Any] = {
            "annotations": {"litterbox.io/updated-at": utcnow().isoformat()}
        }
        if ttl_expired:
            metadata["annotations"]["litterbox.io/ttl-suspended-at"] = utcnow().isoformat()
        self.crd.patch(sandbox_id, {"metadata": metadata, "spec": {"state": "Paused"}})

    def resume(self, sandbox_id: str, *, ttl_seconds: int) -> None:
        spec: dict[str, Any] = {"state": "Running"}
        if ttl_seconds > 0:
            spec["ttlAnchor"] = utcnow().isoformat()
        self.crd.patch(
            sandbox_id,
            {
                "metadata": {
                    "annotations": {
                        "litterbox.io/updated-at": utcnow().isoformat(),
                        "litterbox.io/ttl-suspended-at": None,
                    }
                },
                "spec": spec,
            },
        )

    def set_pool_state(self, sandbox_id: str, pool_state: str) -> None:
        self.crd.patch(
            sandbox_id,
            {
                "metadata": {
                    "labels": {"litterbox.io/pool-state": pool_state},
                    "annotations": {"litterbox.io/updated-at": utcnow().isoformat()},
                }
            },
        )

    def lock(self, sandbox_id: str) -> None:
        now = utcnow().isoformat()
        self.crd.patch(
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
        self.crd.patch(
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
        self.crd.delete(sandbox_id)

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_cr(self, sandbox_id: str) -> dict[str, Any]:
        return self.crd.get(sandbox_id)

    def get(self, sandbox_id: str) -> Sandbox:
        return self.to_sandbox(self.crd.get(sandbox_id))

    def list(self, label_selector: str = "") -> list[Sandbox]:
        return [self.to_sandbox(item) for item in self.crd.list(label_selector)]

    def to_sandbox(self, cr: dict[str, Any]) -> Sandbox:
        metadata = cr.get("metadata") or {}
        labels = metadata.get("labels") or {}
        annotations = metadata.get("annotations") or {}
        spec = cr.get("spec") or {}
        status = cr.get("status") or {}

        created_at = _parse_timestamp(metadata.get("creationTimestamp")) or utcnow()
        updated_at = (
            _parse_timestamp(annotations.get("litterbox.io/updated-at")) or created_at
        )
        ttl_seconds = int(spec.get("ttlSeconds") or 0)
        expires_at = None
        if ttl_seconds > 0:
            anchor = _parse_timestamp(spec.get("ttlAnchor"))
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

        allocated_at = _parse_timestamp(annotations.get("litterbox.io/allocated-at"))

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
            allocated_at=allocated_at,
            created_at=created_at,
            updated_at=updated_at,
            ttl_seconds=ttl_seconds,
            expires_at=expires_at,
            locked=annotations.get("litterbox.io/resume-locked") == "true",
            workspace=workspace,
        )

    def wait_until_running(self, sandbox_id: str, timeout_seconds: float = 5.0) -> None:
        self.crd.wait_until_phase(
            sandbox_id, {"Running"}, timeout_seconds=timeout_seconds
        )

    def wait_until_paused(self, sandbox_id: str, timeout_seconds: float = 5.0) -> None:
        self.crd.wait_until_phase(
            sandbox_id, {"Paused"}, timeout_seconds=timeout_seconds
        )


def workspace_claim_name(sandbox_id: str) -> str:
    return f"workspace-{sandbox_id}"


def extract_metadata(
    labels: dict[str, str], annotations: dict[str, str]
) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for key, value in labels.items():
        if key.startswith("litterbox.io/user-"):
            metadata[key.removeprefix("litterbox.io/user-")] = value
    for key, value in annotations.items():
        if key.startswith("litterbox.io/user-metadata-"):
            metadata[key.removeprefix("litterbox.io/user-metadata-")] = value
    return metadata
