from __future__ import annotations

from types import SimpleNamespace

from orchestrator.domain.models import SandboxStatus, Template, utcnow
from orchestrator.services.sandboxes import SandboxService


def build_template(lifecycle: dict | None = None) -> Template:
    now = utcnow()
    return Template.model_validate(
        {
            "id": "tpl-lifecycle",
            "name": "Lifecycle template",
            "image": "alpine:3.19",
            "command": "sleep 3600",
            "cpu_millicores": 500,
            "memory_mb": 512,
            "lifecycle": lifecycle,
            "created_at": now,
            "updated_at": now,
        }
    )


def build_service() -> SandboxService:
    service = object.__new__(SandboxService)
    service.gateway = SimpleNamespace(
        namespace="default",
        available_runtime_classes=set(),
        secret_exists=lambda name: False,
    )
    service.settings = SimpleNamespace(
        kubernetes=SimpleNamespace(
            runtime_class="",
            image_pull_secret="",
        )
    )
    return service


def test_build_deployment_maps_template_lifecycle_to_pod_spec() -> None:
    service = build_service()
    template = build_template(
        {
            "postStart": {"exec": {"command": ["/bin/sh", "-lc", "echo started"]}},
            "preStop": {
                "exec": {"command": ["/bin/sh", "-lc", "echo stopping"]},
                "terminationGracePeriodSeconds": 30,
            },
        }
    )

    deployment = service._build_deployment(
        sandbox_id="sbx-lifecycle",
        template=template,
        metadata={},
        name="",
        pool_state="none",
        ttl_seconds=None,
    )

    pod_spec = deployment.spec.template.spec
    container = pod_spec.containers[0]
    assert pod_spec.termination_grace_period_seconds == 30
    assert container.lifecycle.post_start._exec.command == ["/bin/sh", "-lc", "echo started"]
    assert container.lifecycle.pre_stop._exec.command == ["/bin/sh", "-lc", "echo stopping"]


def test_delete_sandbox_uses_template_pre_stop_grace_period() -> None:
    template = build_template(
        {
            "preStop": {
                "exec": {"command": ["/bin/sh", "-lc", "echo stopping"]},
                "terminationGracePeriodSeconds": 45,
            }
        }
    )
    deleted: dict[str, object] = {}

    service = object.__new__(SandboxService)
    service._unschedule_current_ttl = lambda sandbox_id: None
    service.get_sandbox = lambda sandbox_id: SimpleNamespace(
        id=sandbox_id,
        template_id=template.id,
        status=SandboxStatus.RUNNING,
    )
    service.template_service = SimpleNamespace(get_template=lambda template_id: template)
    service.expose_service = None
    service.gateway = SimpleNamespace(
        namespace="default",
        list_services=lambda selector: [],
        delete_deployment=lambda name, grace_period_seconds=0: deleted.update(
            {"name": name, "grace_period_seconds": grace_period_seconds}
        ),
    )
    service.webhook_dispatcher = SimpleNamespace(dispatch=lambda **kwargs: None)

    service.delete_sandbox("sbx-lifecycle")

    assert deleted == {"name": "sbx-lifecycle", "grace_period_seconds": 45}


def test_delete_sandbox_defaults_to_zero_grace_without_lifecycle() -> None:
    template = build_template()
    deleted: dict[str, object] = {}

    service = object.__new__(SandboxService)
    service._unschedule_current_ttl = lambda sandbox_id: None
    service.get_sandbox = lambda sandbox_id: SimpleNamespace(id=sandbox_id, template_id=template.id)
    service.template_service = SimpleNamespace(get_template=lambda template_id: template)
    service.expose_service = None
    service.gateway = SimpleNamespace(
        namespace="default",
        list_services=lambda selector: [],
        delete_deployment=lambda name, grace_period_seconds=0: deleted.update(
            {"name": name, "grace_period_seconds": grace_period_seconds}
        ),
    )
    service.webhook_dispatcher = SimpleNamespace(dispatch=lambda **kwargs: None)

    service.delete_sandbox("sbx-no-lifecycle")

    assert deleted == {"name": "sbx-no-lifecycle", "grace_period_seconds": 0}
