from __future__ import annotations

import time

from orchestrator.config import Settings
from orchestrator.domain.models import (
    PoolState,
    QueryOptions,
    Sandbox,
    SandboxListResponse,
    SandboxResponse,
    SandboxStatus,
    Template,
    UpdateSandboxRequest,
    WebhookEvent,
    WorkspaceConfig,
    WorkspaceConfigOverride,
)
from orchestrator.infra.kubernetes import KubernetesGateway
from orchestrator.infra.sandbox_crd import SandboxCRDGateway
from orchestrator.services.sandbox_crd import SandboxCRDService
from orchestrator.services.templates import TemplateService
from orchestrator.services.webhooks import WebhookDispatcher
from orchestrator.utils import is_valid_label_part, short_id


class SandboxResumeLockedError(RuntimeError):
    pass


class SandboxService:
    """Writes Sandbox custom resources and reads controller-written status."""

    def __init__(
        self,
        gateway: KubernetesGateway,
        template_service: TemplateService,
        webhook_dispatcher: WebhookDispatcher,
        settings: Settings,
    ) -> None:
        self.gateway = gateway
        self.template_service = template_service
        self.webhook_dispatcher = webhook_dispatcher
        self.settings = settings
        self.crd = SandboxCRDService(
            settings,
            gateway,
            SandboxCRDGateway(gateway, settings),
        )
        # Set after construction to avoid a circular dependency with
        # ServiceExposeService (which itself holds a SandboxService reference).
        # container.py calls sandbox_service.expose_service = expose_service
        # after both objects have been built.
        self.expose_service = None

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
        workspace: WorkspaceConfigOverride | None = None,
    ) -> SandboxResponse:
        from orchestrator.services.metrics import sandbox_metrics  # 延迟导入，避免循环

        metadata = metadata or {}
        template = self.template_service.get_template(template_id)
        sandbox_id = short_id()
        resolved_workspace = self._resolve_workspace(template, workspace)
        self.crd.create(
            sandbox_id=sandbox_id,
            template=template,
            metadata=metadata,
            name=name,
            env=env,
            pool_state=pool_state,
            ttl_seconds=ttl_seconds,
            workspace=resolved_workspace,
        )

        pod = None
        # 只对用户直接等待的路径（wait_ready=True）记录指标；
        # Pool 预热使用 wait_ready=False，不计入用户体验耗时。
        if wait_ready:
            _t0 = time.perf_counter()
            _success = False
            try:
                pod = self.gateway.wait_for_pod_ready(
                    f"app={sandbox_id},component=sandbox"
                )
                _success = True
            finally:
                sandbox_metrics.record_create(
                    template_id=template_id,
                    duration=time.perf_counter() - _t0,
                    success=_success,
                    source="direct",
                )
            # The Pod is already serving; a status update that arrives a moment
            # later must not make the create response look unfinished.
            self.crd.wait_until_running(sandbox_id)

        sandbox = self.get_sandbox(sandbox_id)
        if dispatch_events and pool_state == PoolState.NONE:
            self._dispatch_running_events(sandbox, template, pod)
        return sandbox

    def build_pool_template(
        self,
        template: Template,
        workspace: WorkspaceConfig,
    ) -> dict:
        return self.crd.build_pool_template(template=template, workspace=workspace)

    def claim_pool_sandbox(
        self,
        *,
        pool_name: str,
        name: str,
        metadata: dict[str, str],
        ttl_seconds: int,
    ) -> SandboxResponse | None:
        sandbox = self.crd.claim_available(
            pool_name,
            name=name,
            metadata=metadata,
            ttl_seconds=ttl_seconds,
        )
        if sandbox is None:
            return None
        return self.get_sandbox(sandbox.id)

    def detach_pool_sandboxes(self, pool_name: str) -> None:
        self.crd.detach_pool_allocated(pool_name)

    def get_sandbox(self, sandbox_id: str) -> SandboxResponse:
        sandbox = self.crd.get(sandbox_id)
        try:
            template = self.template_service.get_template(sandbox.template_id)
        except Exception:
            template = None
        return SandboxResponse.from_sandbox(sandbox, template)

    def list_sandboxes(self, opts: QueryOptions) -> SandboxListResponse:
        label_selector = self._sandbox_label_selector(opts)
        return self._sandbox_list_response(self.crd.list(label_selector), opts)

    def status_counts(self) -> dict[str, int]:
        counts = {"total": 0, "running": 0, "stopped": 0, "creating": 0}
        for sandbox in self.crd.list("component=sandbox"):
            counts["total"] += 1
            if sandbox.status == SandboxStatus.RUNNING:
                counts["running"] += 1
            elif sandbox.status in {SandboxStatus.STOPPED, SandboxStatus.EXITED}:
                counts["stopped"] += 1
            elif sandbox.status in {SandboxStatus.CREATED, SandboxStatus.CREATING}:
                counts["creating"] += 1
        return counts

    @staticmethod
    def _sandbox_label_selector(opts: QueryOptions) -> str:
        # Fields that CAN be pushed down (stored as labels):
        #   - component=sandbox  (always)
        #   - litterbox.io/template-id
        #   - litterbox.io/pool-state  (when pool_state != PoolState.NONE)
        #
        # status/name/metadata are filtered in memory because they are derived
        # from status or stored as annotations.
        selector_parts = ["component=sandbox"]
        if opts.template_id:
            selector_parts.append(f"litterbox.io/template-id={opts.template_id}")
        if opts.pool_state and opts.pool_state != PoolState.NONE:
            selector_parts.append(f"litterbox.io/pool-state={opts.pool_state}")
        elif opts.pool_state == PoolState.NONE:
            selector_parts.append("!litterbox.io/pool-state")
        return ",".join(selector_parts)

    def _sandbox_list_response(
        self,
        sandboxes: list[Sandbox],
        opts: QueryOptions,
    ) -> SandboxListResponse:
        responses: list[SandboxResponse] = []
        template_cache: dict[str, Template] = {}
        for sandbox in sandboxes:
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
            responses.append(SandboxResponse.from_sandbox(sandbox, template))

        responses.sort(key=lambda item: item.created_at, reverse=True)
        total = len(responses)
        start = max(opts.page - 1, 0) * opts.page_size
        end = start + opts.page_size
        return SandboxListResponse(
            total=total,
            page=opts.page,
            page_size=opts.page_size,
            sandboxes=responses[start:end],
        )

    def update_sandbox(self, sandbox_id: str, req: UpdateSandboxRequest) -> SandboxResponse:
        cr = self.crd.get_cr(sandbox_id)
        cr_metadata = cr.get("metadata") or {}
        labels = dict(cr_metadata.get("labels") or {})
        annotations = dict(cr_metadata.get("annotations") or {})
        self._apply_user_updates(req, labels=labels, annotations=annotations)
        self.crd.patch_metadata(sandbox_id, labels=labels, annotations=annotations)
        return self.get_sandbox(sandbox_id)

    def delete_sandbox(self, sandbox_id: str, deletion_reason: str = "manual") -> None:
        sandbox = self.get_sandbox(sandbox_id)
        try:
            template = self.template_service.get_template(sandbox.template_id)
        except Exception:
            template = None
        if self.expose_service is not None:
            self.expose_service.delete_exposes_for_sandbox(sandbox_id)
        self.webhook_dispatcher.dispatch(
            event=WebhookEvent.SANDBOX_DELETED,
            sandbox=sandbox,
            template=template,
            namespace=self.gateway.namespace,
            deletion_reason=deletion_reason,
        )
        # Pod and PVC carry an ownerReference to the Sandbox, so Kubernetes
        # garbage collection removes them with the CR.
        self.crd.delete(sandbox_id)

    def suspend_sandbox(self, sandbox_id: str, *, ttl_expired: bool = False) -> SandboxResponse:
        self.crd.suspend(sandbox_id, ttl_expired=ttl_expired)
        self.crd.wait_until_paused(sandbox_id)
        return self.get_sandbox(sandbox_id)

    def resume_sandbox(self, sandbox_id: str) -> SandboxResponse:
        cr = self.crd.get_cr(sandbox_id)
        annotations = (cr.get("metadata") or {}).get("annotations") or {}
        if annotations.get("litterbox.io/resume-locked") == "true":
            raise SandboxResumeLockedError(
                f"sandbox {sandbox_id} is locked and cannot be resumed"
            )
        ttl_seconds = int((cr.get("spec") or {}).get("ttlSeconds") or 0)
        self.crd.resume(sandbox_id, ttl_seconds=ttl_seconds)
        self.gateway.wait_for_pod_ready(f"app={sandbox_id},component=sandbox")
        self.crd.wait_until_running(sandbox_id)
        return self.get_sandbox(sandbox_id)

    def lock_sandbox(self, sandbox_id: str) -> SandboxResponse:
        self.crd.lock(sandbox_id)
        return self.get_sandbox(sandbox_id)

    def unlock_sandbox(self, sandbox_id: str) -> SandboxResponse:
        self.crd.unlock(sandbox_id)
        return self.get_sandbox(sandbox_id)

    def update_ttl(self, sandbox_id: str, ttl_seconds: int) -> None:
        self.crd.set_ttl(sandbox_id, ttl_seconds)

    def renew_ttl(self, sandbox_id: str, ttl_seconds: int = 0) -> None:
        cr = self.crd.get_cr(sandbox_id)
        current_ttl = int((cr.get("spec") or {}).get("ttlSeconds") or 0)
        if current_ttl == 0:
            raise ValueError("sandbox does not have TTL enabled")
        self.crd.renew_ttl(
            sandbox_id,
            ttl_seconds=ttl_seconds,
            current_ttl=current_ttl,
        )

    def _resolve_workspace(
        self,
        template: Template,
        override: WorkspaceConfigOverride | None,
    ) -> WorkspaceConfig:
        resolved: dict[str, str | bool | None] = {
            "enabled": self.settings.workspace.enabled,
            "mount_path": self.settings.workspace.mount_path,
            "size": self.settings.workspace.default_size,
            "storage_class": (
                self.settings.workspace.storage_class or self.settings.kubernetes.storage_class or None
            ),
        }
        for policy in (template.workspace, override):
            if policy is not None:
                resolved.update(policy.model_dump(exclude_none=True))
        return WorkspaceConfig.model_validate(resolved)

    @staticmethod
    def _apply_user_updates(
        req: UpdateSandboxRequest,
        *,
        labels: dict[str, str],
        annotations: dict[str, str],
    ) -> None:
        if req.metadata:
            for key, value in req.metadata.items():
                label_key = f"litterbox.io/user-{key}"
                annotation_key = f"litterbox.io/user-metadata-{key}"
                if is_valid_label_part(key) and is_valid_label_part(value):
                    labels[label_key] = value
                    annotations.pop(annotation_key, None)
                else:
                    annotations[annotation_key] = value
                    labels.pop(label_key, None)

        if req.name:
            annotations["litterbox.io/allocated-name"] = req.name

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
