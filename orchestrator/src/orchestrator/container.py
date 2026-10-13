from __future__ import annotations

from dataclasses import dataclass

from orchestrator.config import Settings, get_settings
from orchestrator.infra.kubernetes import KubernetesGateway
from orchestrator.infra.repositories import PoolRepository, TemplateRepository, WebhookRepository
from orchestrator.infra.ttl_queue import TTLQueueRepository
from orchestrator.services.envd_proxy import EnvdProxyService
from orchestrator.services.e2b import E2BControlPlaneService
from orchestrator.services.exposes import ServiceExposeService
from orchestrator.services.pools import PoolService
from orchestrator.services.sandboxes import SandboxService
from orchestrator.services.templates import TemplateService
from orchestrator.services.ttl import TTLWorker
from orchestrator.services.webhooks import WebhookDispatcher, WebhookService


@dataclass
class Container:
    settings: Settings
    gateway: KubernetesGateway
    template_service: TemplateService
    webhook_service: WebhookService
    ttl_queue: TTLQueueRepository
    sandbox_service: SandboxService
    pool_service: PoolService
    expose_service: ServiceExposeService
    ttl_worker: TTLWorker
    envd_proxy_service: EnvdProxyService
    e2b_service: E2BControlPlaneService


def build_container(settings: Settings | None = None) -> Container:
    settings = settings or get_settings()
    gateway = KubernetesGateway(settings)
    template_repository = TemplateRepository(gateway)
    pool_repository = PoolRepository(gateway)
    webhook_repository = WebhookRepository(gateway)
    ttl_queue = TTLQueueRepository(settings.celery.broker_url, settings.ttl.queue_key)
    template_service = TemplateService(template_repository)
    webhook_service = WebhookService(webhook_repository, settings)
    dispatcher = WebhookDispatcher(webhook_repository, settings)
    sandbox_service = SandboxService(gateway, template_service, dispatcher, ttl_queue, settings)
    pool_service = PoolService(pool_repository, sandbox_service, template_service, settings.celery.broker_url)
    expose_service = ServiceExposeService(gateway, sandbox_service, settings)
    sandbox_service.expose_service = expose_service
    ttl_worker = TTLWorker(ttl_queue, sandbox_service, settings.ttl.worker_poll_interval_seconds)
    envd_proxy_service = EnvdProxyService(settings, gateway)
    e2b_service = E2BControlPlaneService(settings, sandbox_service, pool_service)
    return Container(
        settings=settings,
        gateway=gateway,
        template_service=template_service,
        webhook_service=webhook_service,
        ttl_queue=ttl_queue,
        sandbox_service=sandbox_service,
        pool_service=pool_service,
        expose_service=expose_service,
        ttl_worker=ttl_worker,
        envd_proxy_service=envd_proxy_service,
        e2b_service=e2b_service,
    )
