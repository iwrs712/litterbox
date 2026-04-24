from __future__ import annotations

import shlex
import time
from datetime import UTC, datetime

from kubernetes import client
from kubernetes.client import ApiException

from orchestrator.config import Settings
from orchestrator.domain.models import (
    AllocateSandboxRequest,
    ExecCommandRequest,
    ExecCommandResult,
    PoolState,
    QueryOptions,
    Sandbox,
    SandboxListResponse,
    SandboxResponse,
    SandboxStatus,
    Template,
    UpdateSandboxRequest,
    WebhookEvent,
)
from orchestrator.infra.kubernetes import KubernetesGateway
from orchestrator.infra.ttl_queue import TTLEntry, TTLQueueRepository
from orchestrator.services.templates import TemplateService
from orchestrator.services.webhooks import WebhookDispatcher
from orchestrator.utils import is_valid_label_part, parse_env_list, short_id, utcnow


class SandboxService:
    def __init__(
        self,
        gateway: KubernetesGateway,
        template_service: TemplateService,
        webhook_dispatcher: WebhookDispatcher,
        ttl_queue: TTLQueueRepository,
        settings: Settings,
    ) -> None:
        self.gateway = gateway
        self.template_service = template_service
        self.webhook_dispatcher = webhook_dispatcher
        self.ttl_queue = ttl_queue
        self.settings = settings
        # Set after construction to avoid a circular dependency with
        # ServiceExposeService (which itself holds a SandboxService reference).
        # container.py calls  sandbox_service.expose_service = expose_service
        # after both objects have been built.
        self.expose_service: "ServiceExposeService | None" = None  # type: ignore[name-defined]

    def get_template(self, template_id: str) -> Template:
        return self.template_service.get_template(template_id)

    def create_sandbox(
        self,
        *,
        template_id: str,
        name: str = "",
        metadata: dict[str, str] | None = None,
        env: list[str] | None = None,
        pool_state: str = PoolState.NONE,
        wait_ready: bool = True,
        dispatch_events: bool = True,
        ttl_seconds: int | None = None,
    ) -> SandboxResponse:
        from orchestrator.services.metrics import sandbox_metrics  # 延迟导入，避免循环

        metadata = metadata or {}
        template = self.template_service.get_template(template_id)
        sandbox_id = short_id()
        deployment = self._build_deployment(
            sandbox_id=sandbox_id,
            template=template,
            metadata=metadata,
            name=name,
            env=env,
            pool_state=pool_state,
            ttl_seconds=ttl_seconds,
        )
        self.gateway.create_deployment(deployment)
        self._sync_ttl_schedule(sandbox_id, deployment.metadata.annotations or {})
        pod = None
        # 只对用户直接等待的路径（wait_ready=True）记录指标；
        # Pool 预热使用 wait_ready=False，不计入用户体验耗时。
        if wait_ready:
            _t0 = time.perf_counter()
            _success = False
            try:
                pod = self.gateway.wait_for_pod_ready(f"app={sandbox_id},component=sandbox")
                _success = True
            finally:
                sandbox_metrics.record_create(
                    template_id=template_id,
                    duration=time.perf_counter() - _t0,
                    success=_success,
                    source="direct",
                )
        sandbox = self.get_sandbox(sandbox_id)
        if dispatch_events and pool_state == PoolState.NONE:
            self._dispatch_running_events(sandbox, template, pod)
        return sandbox

    def get_sandbox(self, sandbox_id: str) -> SandboxResponse:
        deployment = self.gateway.read_deployment(sandbox_id)
        sandbox = self._deployment_to_sandbox(deployment)
        try:
            template = self.template_service.get_template(sandbox.template_id)
        except Exception:
            template = None
        return SandboxResponse.from_sandbox(sandbox, template)

    def list_sandboxes(self, opts: QueryOptions) -> SandboxListResponse:
        # ── K8s label-selector push-down ────────────────────────────────────
        # Build the selector from fields that are stored as K8s labels so that
        # the K8s API server does the heavy lifting instead of us fetching every
        # sandbox and filtering in Python.
        #
        # Fields that CAN be pushed down (stored as labels):
        #   - component=sandbox  (always)
        #   - litterbox.io/template-id
        #   - litterbox.io/pool-state  (when pool_state != PoolState.NONE)
        #
        # Fields that CANNOT be pushed down (stored in annotations or derived
        # from Deployment status at read-time):
        #   - status   (derived from spec.replicas / status.readyReplicas)
        #   - name     (annotation litterbox.io/allocated-name)
        #   - metadata (annotation litterbox.io/user-metadata-*)
        # These are filtered below in Python after the K8s list.
        selector_parts = ["component=sandbox"]
        if opts.template_id:
            selector_parts.append(f"litterbox.io/template-id={opts.template_id}")
        if opts.pool_state and opts.pool_state != PoolState.NONE:
            selector_parts.append(f"litterbox.io/pool-state={opts.pool_state}")
        elif opts.pool_state == PoolState.NONE:
            # NONE means "not pool-managed"; those deployments have no pool-state
            # label at all, so we can filter them out by excluding managed ones.
            selector_parts.append("!litterbox.io/pool-state")

        label_selector = ",".join(selector_parts)
        deployments = self.gateway.list_deployments(label_selector)

        sandboxes: list[SandboxResponse] = []
        template_cache: dict[str, Template] = {}
        for deployment in deployments:
            sandbox = self._deployment_to_sandbox(deployment)
            # ── remaining in-memory filters ──────────────────────────────────
            if opts.status and sandbox.status != opts.status:
                continue
            if opts.name and opts.name not in sandbox.name:
                continue
            if opts.metadata:
                if any(sandbox.metadata.get(key) != value for key, value in opts.metadata.items()):
                    continue
                # When filtering by metadata (e.g. upstream querying by user_id),
                # exclude stopped sandboxes unless an explicit status filter is set.
                if not opts.status and sandbox.status == SandboxStatus.STOPPED:
                    continue
            template = template_cache.get(sandbox.template_id)
            if template is None:
                try:
                    template = self.template_service.get_template(sandbox.template_id)
                except Exception:
                    template = None
                if template is not None:
                    template_cache[sandbox.template_id] = template
            sandboxes.append(SandboxResponse.from_sandbox(sandbox, template))

        sandboxes.sort(key=lambda item: item.created_at, reverse=True)
        total = len(sandboxes)
        start = max(opts.page - 1, 0) * opts.page_size
        end = start + opts.page_size
        return SandboxListResponse(
            total=total,
            page=opts.page,
            page_size=opts.page_size,
            sandboxes=sandboxes[start:end],
        )

    def update_sandbox(self, sandbox_id: str, req: UpdateSandboxRequest) -> SandboxResponse:
        deployment = self.gateway.read_deployment(sandbox_id)
        labels = dict(deployment.metadata.labels or {})
        annotations = dict(deployment.metadata.annotations or {})

        self._apply_user_updates(
            req,
            labels=labels,
            annotations=annotations,
        )
        self._patch_deployment_metadata(
            sandbox_id,
            labels=labels,
            annotations=annotations,
        )
        return self.get_sandbox(sandbox_id)

    def update_pool_state(self, sandbox_id: str, pool_state: str) -> None:
        deployment = self.gateway.read_deployment(sandbox_id)
        labels = {**(deployment.metadata.labels or {}), "litterbox.io/pool-state": pool_state}
        self._patch_deployment_metadata(sandbox_id, labels=labels)

    def mark_pool_allocated(
        self,
        sandbox_id: str,
        *,
        name: str,
        metadata: dict[str, str],
        ttl_seconds: int,
    ) -> SandboxResponse:
        deployment = self.gateway.read_deployment(sandbox_id)
        labels = dict(deployment.metadata.labels or {})
        annotations = dict(deployment.metadata.annotations or {})
        previous_token = annotations.get("litterbox.io/ttl-token", "")
        self._apply_user_updates(
            UpdateSandboxRequest(name=name, metadata=metadata),
            labels=labels,
            annotations=annotations,
        )
        labels["litterbox.io/pool-state"] = PoolState.ALLOCATED
        annotations["litterbox.io/allocated-at"] = utcnow().isoformat()
        self._apply_ttl_annotations(annotations, ttl_seconds)
        self._patch_deployment_metadata(
            sandbox_id,
            labels=labels,
            annotations=annotations,
        )
        self._sync_ttl_schedule(sandbox_id, annotations, previous_token=previous_token)
        return self.get_sandbox(sandbox_id)

    def delete_sandbox(self, sandbox_id: str, deletion_reason: str = "manual") -> None:
        self._unschedule_current_ttl(sandbox_id)
        sandbox = self.get_sandbox(sandbox_id)
        try:
            template = self.template_service.get_template(sandbox.template_id)
        except Exception:
            template = None
        grace_period_seconds = self._termination_grace_period_seconds(template)
        # Delegate expose resource cleanup to ServiceExposeService so that the
        # naming convention (svc-/ing- prefix) lives in exactly one place.
        if self.expose_service is not None:
            self.expose_service.delete_exposes_for_sandbox(sandbox_id)
        else:
            # Fallback: ServiceExposeService not wired yet (e.g. in tests).
            # Replicate the minimal cleanup inline so delete_sandbox still works.
            services = self.gateway.list_services(f"litterbox.io/sandbox-id={sandbox_id}")
            for svc in services:
                expose_id = (svc.metadata.labels or {}).get("litterbox.io/expose-id")
                if expose_id:
                    self.gateway.delete_ingress(f"ing-{expose_id}")
                self.gateway.delete_service(svc.metadata.name)
        self.webhook_dispatcher.dispatch(
            event=WebhookEvent.SANDBOX_DELETED,
            sandbox=sandbox,
            template=template,
            namespace=self.gateway.namespace,
            deletion_reason=deletion_reason,
        )
        self.gateway.delete_deployment(sandbox_id, grace_period_seconds=grace_period_seconds)

    def exec_command(self, sandbox_id: str, command: list[str]) -> ExecCommandResult:
        from orchestrator.services.workspace import WorkspaceService
        request = ExecCommandRequest(command=command)
        return WorkspaceService(self.gateway).exec_command(sandbox_id, request)

    def update_ttl(self, sandbox_id: str, ttl_seconds: int) -> None:
        deployment = self.gateway.read_deployment(sandbox_id)
        annotations = dict(deployment.metadata.annotations or {})
        previous_token = annotations.get("litterbox.io/ttl-token", "")
        self._apply_ttl_annotations(annotations, ttl_seconds)
        self._patch_deployment_metadata(sandbox_id, annotations=annotations)
        self._sync_ttl_schedule(sandbox_id, annotations, previous_token=previous_token)

    def renew_ttl(self, sandbox_id: str, ttl_seconds: int = 0) -> None:
        deployment = self.gateway.read_deployment(sandbox_id)
        annotations = dict(deployment.metadata.annotations or {})
        current_ttl = int(annotations.get("litterbox.io/ttl-seconds", "0"))
        if current_ttl == 0:
            raise ValueError("sandbox does not have TTL enabled")
        effective_ttl = ttl_seconds or current_ttl
        previous_token = annotations.get("litterbox.io/ttl-token", "")
        self._apply_ttl_annotations(annotations, effective_ttl, include_ttl=False)
        annotations["litterbox.io/last-ttl-renewal"] = utcnow().isoformat()
        self._patch_deployment_metadata(sandbox_id, annotations=annotations)
        self._sync_ttl_schedule(sandbox_id, annotations, previous_token=previous_token)

    def cleanup_expired(self) -> int:
        deleted = 0
        for deployment in self.gateway.list_deployments("component=sandbox"):
            annotations = deployment.metadata.annotations or {}
            expires_at = annotations.get("litterbox.io/expires-at")
            if not expires_at:
                continue
            if datetime.fromisoformat(expires_at) <= utcnow():
                self.delete_sandbox(deployment.metadata.name, deletion_reason="ttl_expired")
                deleted += 1
        return deleted

    def delete_if_ttl_due(self, sandbox_id: str, ttl_token: str) -> bool:
        try:
            deployment = self.gateway.read_deployment(sandbox_id)
        except ApiException as exc:
            if exc.status == 404:
                return False
            raise
        annotations = deployment.metadata.annotations or {}
        if annotations.get("litterbox.io/ttl-token", "") != ttl_token:
            return False
        expires_at = annotations.get("litterbox.io/expires-at")
        if not expires_at or datetime.fromisoformat(expires_at) > utcnow():
            return False
        self.delete_sandbox(sandbox_id, deletion_reason="ttl_expired")
        return True

    def _build_deployment(
        self,
        *,
        sandbox_id: str,
        template: Template,
        metadata: dict[str, str],
        name: str,
        env: list[str] | None,
        pool_state: str,
        ttl_seconds: int | None,
    ) -> client.V1Deployment:
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
        }
        if name:
            annotations["litterbox.io/allocated-name"] = name
        for key, value in metadata.items():
            if is_valid_label_part(key) and is_valid_label_part(value):
                labels[f"litterbox.io/user-{key}"] = value
            else:
                annotations[f"litterbox.io/user-metadata-{key}"] = value

        effective_ttl = ttl_seconds if ttl_seconds is not None else (template.ttl_seconds or 0)
        if effective_ttl > 0:
            self._set_ttl_annotations(annotations, effective_ttl, ttl_token=short_id("ttl-"))

        merged_env_items = [*template.env, *(env or [])]
        merged_env_map: dict[str, str] = {}
        for key, value in parse_env_list(merged_env_items):
            merged_env_map[key] = value
        container_env = [client.V1EnvVar(name=key, value=value) for key, value in merged_env_map.items()]
        volume_mounts: list[client.V1VolumeMount] = []
        volumes: list[client.V1Volume] = []
        for index, mount in enumerate(template.host_path_mounts):
            volume_name = f"host-mount-{index}"
            volumes.append(
                client.V1Volume(
                    name=volume_name,
                    host_path=client.V1HostPathVolumeSource(
                        path=mount.host_path,
                        type="DirectoryOrCreate",
                    ),
                )
            )
            volume_mounts.append(
                client.V1VolumeMount(
                    name=volume_name,
                    mount_path=mount.container_path,
                    read_only=mount.read_only,
                )
            )

        resources = client.V1ResourceRequirements(
            limits={
                "cpu": f"{template.cpu_millicores}m",
                "memory": f"{template.memory_mb}Mi",
            },
            requests={
                "cpu": f"{template.cpu_request or template.cpu_millicores}m",
                "memory": f"{template.memory_request or template.memory_mb}Mi",
            },
        )
        lifecycle = self._build_container_lifecycle(template)
        termination_grace_period_seconds = self._termination_grace_period_seconds(template)
        pod_spec = client.V1PodSpec(
            runtime_class_name=(
                self.settings.kubernetes.runtime_class
                if self.settings.kubernetes.runtime_class in self.gateway.available_runtime_classes
                else None
            ),
            image_pull_secrets=(
                [client.V1LocalObjectReference(name=self.settings.kubernetes.image_pull_secret)]
                if self.settings.kubernetes.image_pull_secret
                and self.gateway.secret_exists(self.settings.kubernetes.image_pull_secret)
                else None
            ),
            restart_policy="Always",
            volumes=volumes or None,
            termination_grace_period_seconds=termination_grace_period_seconds or None,
            containers=[
                client.V1Container(
                    name="main",
                    image=template.image,
                    command=shlex.split(template.command) if template.command else None,
                    env=container_env or None,
                    lifecycle=lifecycle,
                    resources=resources,
                    volume_mounts=volume_mounts or None,
                    stdin=True,
                    stdin_once=False,
                    tty=True,
                    image_pull_policy="IfNotPresent",
                )
            ],
        )
        return client.V1Deployment(
            metadata=client.V1ObjectMeta(
                name=sandbox_id,
                namespace=self.gateway.namespace,
                labels=labels,
                annotations=annotations,
            ),
            spec=client.V1DeploymentSpec(
                replicas=1,
                selector=client.V1LabelSelector(match_labels={"app": sandbox_id}),
                template=client.V1PodTemplateSpec(
                    metadata=client.V1ObjectMeta(labels=labels, annotations=annotations),
                    spec=pod_spec,
                ),
            ),
        )

    @staticmethod
    def _build_container_lifecycle(template: Template) -> client.V1Lifecycle | None:
        if template.lifecycle is None:
            return None

        post_start = None
        if template.lifecycle.post_start is not None:
            post_start = client.V1LifecycleHandler(
                _exec=client.V1ExecAction(command=template.lifecycle.post_start.exec.command)
            )

        pre_stop = None
        if template.lifecycle.pre_stop is not None:
            pre_stop = client.V1LifecycleHandler(
                _exec=client.V1ExecAction(command=template.lifecycle.pre_stop.exec.command)
            )

        return client.V1Lifecycle(post_start=post_start, pre_stop=pre_stop)

    @staticmethod
    def _termination_grace_period_seconds(template: Template | None) -> int:
        if template is None or template.lifecycle is None or template.lifecycle.pre_stop is None:
            return 0
        return template.lifecycle.pre_stop.termination_grace_period_seconds or 0

    def _deployment_to_sandbox(self, deployment: client.V1Deployment) -> Sandbox:
        labels = deployment.metadata.labels or {}
        annotations = deployment.metadata.annotations or {}
        name = annotations.get("litterbox.io/allocated-name", deployment.metadata.name)
        ttl_seconds = int(annotations.get("litterbox.io/ttl-seconds", "0"))
        expires_at = None
        if annotations.get("litterbox.io/expires-at"):
            expires_at = datetime.fromisoformat(annotations["litterbox.io/expires-at"])
        allocated_at = None
        if annotations.get("litterbox.io/allocated-at"):
            allocated_at = datetime.fromisoformat(annotations["litterbox.io/allocated-at"])
        updated_at_raw = annotations.get("litterbox.io/updated-at")
        updated_at = datetime.fromisoformat(updated_at_raw) if updated_at_raw else deployment.metadata.creation_timestamp
        return Sandbox(
            id=deployment.metadata.name,
            name=name,
            template_id=labels.get("litterbox.io/template-id", ""),
            status=self._deployment_status_to_sandbox_status(deployment),
            terminating=deployment.metadata.deletion_timestamp is not None,
            pool_state=labels.get("litterbox.io/pool-state", PoolState.NONE),
            metadata=self._extract_metadata(labels, annotations),
            allocated_at=allocated_at,
            created_at=deployment.metadata.creation_timestamp,
            updated_at=updated_at,
            ttl_seconds=ttl_seconds,
            expires_at=expires_at,
        )

    @staticmethod
    def _extract_metadata(labels: dict[str, str], annotations: dict[str, str]) -> dict[str, str]:
        metadata: dict[str, str] = {}
        for key, value in labels.items():
            if key.startswith("litterbox.io/user-"):
                metadata[key.removeprefix("litterbox.io/user-")] = value
        for key, value in annotations.items():
            if key.startswith("litterbox.io/user-metadata-"):
                metadata[key.removeprefix("litterbox.io/user-metadata-")] = value
        return metadata

    @staticmethod
    def _apply_user_updates(
        req: UpdateSandboxRequest,
        *,
        labels: dict[str, str],
        annotations: dict[str, str],
        pod_labels: dict[str, str] | None = None,
        pod_annotations: dict[str, str] | None = None,
    ) -> None:
        if req.metadata:
            for key, value in req.metadata.items():
                label_key = f"litterbox.io/user-{key}"
                annotation_key = f"litterbox.io/user-metadata-{key}"
                if is_valid_label_part(key) and is_valid_label_part(value):
                    labels[label_key] = value
                    if pod_labels is not None:
                        pod_labels[label_key] = value
                    annotations.pop(annotation_key, None)
                    if pod_annotations is not None:
                        pod_annotations.pop(annotation_key, None)
                else:
                    annotations[annotation_key] = value
                    if pod_annotations is not None:
                        pod_annotations[annotation_key] = value
                    labels.pop(label_key, None)
                    if pod_labels is not None:
                        pod_labels.pop(label_key, None)

        if req.name:
            annotations["litterbox.io/allocated-name"] = req.name
            if pod_annotations is not None:
                pod_annotations["litterbox.io/allocated-name"] = req.name

    def _patch_deployment_metadata(
        self,
        sandbox_id: str,
        *,
        labels: dict[str, str] | None = None,
        annotations: dict[str, str] | None = None,
        pod_labels: dict[str, str] | None = None,
        pod_annotations: dict[str, str] | None = None,
    ) -> None:
        body: dict[str, object] = {}
        if labels is not None or annotations is not None:
            metadata: dict[str, object] = {}
            if labels is not None:
                metadata["labels"] = labels
            if annotations is not None:
                # Stamp the real modification time whenever annotations are updated.
                annotations["litterbox.io/updated-at"] = utcnow().isoformat()
                metadata["annotations"] = annotations
            body["metadata"] = metadata
        if pod_labels is not None or pod_annotations is not None:
            template_metadata: dict[str, object] = {}
            if pod_labels is not None:
                template_metadata["labels"] = pod_labels
            if pod_annotations is not None:
                template_metadata["annotations"] = pod_annotations
            body["spec"] = {"template": {"metadata": template_metadata}}
        if body:
            self.gateway.patch_deployment(sandbox_id, body)

    def _apply_ttl_annotations(
        self,
        annotations: dict[str, str],
        ttl_seconds: int,
        *,
        include_ttl: bool = True,
    ) -> None:
        if ttl_seconds <= 0:
            self._clear_ttl_annotations(annotations)
            return
        ttl_token = short_id("ttl-")
        self._set_ttl_annotations(annotations, ttl_seconds, ttl_token=ttl_token, include_ttl=include_ttl)

    @staticmethod
    def _set_ttl_annotations(
        annotations: dict[str, str],
        ttl_seconds: int,
        *,
        ttl_token: str,
        include_ttl: bool = True,
    ) -> None:
        if include_ttl:
            annotations["litterbox.io/ttl-seconds"] = str(ttl_seconds)
        annotations["litterbox.io/expires-at"] = datetime.fromtimestamp(utcnow().timestamp() + ttl_seconds, tz=UTC).isoformat()
        annotations["litterbox.io/ttl-token"] = ttl_token

    @staticmethod
    def _clear_ttl_annotations(annotations: dict[str, str]) -> None:
        for key in ("litterbox.io/ttl-seconds", "litterbox.io/expires-at", "litterbox.io/ttl-token", "litterbox.io/last-ttl-renewal"):
            annotations.pop(key, None)

    def _sync_ttl_schedule(
        self,
        sandbox_id: str,
        annotations: dict[str, str],
        *,
        previous_token: str = "",
    ) -> None:
        current_token = annotations.get("litterbox.io/ttl-token", "")
        if previous_token and previous_token != current_token:
            self.ttl_queue.unschedule(TTLEntry(sandbox_id=sandbox_id, ttl_token=previous_token))
        expires_at = annotations.get("litterbox.io/expires-at")
        if current_token and expires_at:
            self.ttl_queue.schedule(
                TTLEntry(sandbox_id=sandbox_id, ttl_token=current_token),
                datetime.fromisoformat(expires_at),
            )

    def _unschedule_current_ttl(self, sandbox_id: str) -> None:
        try:
            deployment = self.gateway.read_deployment(sandbox_id)
        except Exception:  # noqa: BLE001
            return
        token = (deployment.metadata.annotations or {}).get("litterbox.io/ttl-token", "")
        if token:
            self.ttl_queue.unschedule(TTLEntry(sandbox_id=sandbox_id, ttl_token=token))

    def _dispatch_running_events(self, sandbox: SandboxResponse, template: Template, pod) -> None:
        payload = {
            "sandbox": sandbox,
            "template": template,
            "namespace": self.gateway.namespace,
            "pod_name": pod.metadata.name if pod else "",
            "pod_ip": pod.status.pod_ip if pod else "",
            "node_name": pod.spec.node_name if pod else "",
        }
        self.webhook_dispatcher.dispatch(event=WebhookEvent.SANDBOX_STARTED, **payload)
        self.webhook_dispatcher.dispatch(event=WebhookEvent.SANDBOX_READY, **payload)

    def dispatch_running_events(self, sandbox_id: str) -> None:
        sandbox = self.get_sandbox(sandbox_id)
        template = self.template_service.get_template(sandbox.template_id)
        pod = None
        try:
            pod = self.gateway.get_first_running_pod(sandbox_id)
        except Exception:  # noqa: BLE001
            pod = None
        self._dispatch_running_events(sandbox, template, pod)

    @staticmethod
    def _deployment_status_to_sandbox_status(deployment: client.V1Deployment) -> SandboxStatus:
        replicas = deployment.spec.replicas or 0
        status = deployment.status
        if deployment.metadata.deletion_timestamp is not None:
            return SandboxStatus.STOPPED
        if replicas == 0:
            return SandboxStatus.STOPPED
        if (status.ready_replicas or 0) > 0 and (status.available_replicas or 0) > 0:
            return SandboxStatus.RUNNING
        if (status.unavailable_replicas or 0) > 0 or (status.replicas or 0) == 0:
            return SandboxStatus.CREATED
        if (status.replicas or 0) > 0 and (status.ready_replicas or 0) == 0:
            return SandboxStatus.CREATED
        return SandboxStatus.UNKNOWN
