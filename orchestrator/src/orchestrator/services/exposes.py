from __future__ import annotations

from kubernetes import client
from kubernetes.client import ApiException

from orchestrator.config import Settings
from orchestrator.domain.models import (
    CreateServiceExposeRequest,
    ExposeStatus,
    ProtocolType,
    ServiceExpose,
)
from orchestrator.infra.kubernetes import KubernetesGateway
from orchestrator.services.sandboxes import SandboxService
from orchestrator.utils import short_id, utcnow


class ServiceExposeService:
    def __init__(self, gateway: KubernetesGateway, sandbox_service: SandboxService, settings: Settings) -> None:
        self.gateway = gateway
        self.sandbox_service = sandbox_service
        self.settings = settings

    def create_expose(self, req: CreateServiceExposeRequest) -> ServiceExpose:
        sandbox = self.sandbox_service.get_sandbox(req.sandbox_id)
        if sandbox.status.value != "running":
            raise ValueError(f"sandbox must be running, current status: {sandbox.status}")
        for existing in self.list_exposes(req.sandbox_id):
            if existing.internal_port == req.internal_port and existing.protocol == req.protocol:
                raise ValueError(
                    f"port {req.internal_port} with protocol {req.protocol} is already exposed for this sandbox "
                    f"(expose_id: {existing.id})"
                )

        expose_id = short_id("expose-")
        service_name = f"svc-{expose_id}"
        now = utcnow()
        metadata_annotations = {
            "litterbox.io/created-at": now.isoformat(),
            "litterbox.io/name": req.name,
            "litterbox.io/protocol": req.protocol.value,
            "litterbox.io/internal-port": str(req.internal_port),
        }
        service = client.V1Service(
            metadata=client.V1ObjectMeta(
                name=service_name,
                namespace=self.gateway.namespace,
                labels={
                    "component": "service-expose",
                    "litterbox.io/sandbox-id": req.sandbox_id,
                    "litterbox.io/expose-id": expose_id,
                },
                annotations=metadata_annotations,
            ),
            spec=client.V1ServiceSpec(
                type="ClusterIP" if req.protocol == ProtocolType.HTTP else "NodePort",
                selector={"component": "sandbox", "app": req.sandbox_id},
                ports=[
                    client.V1ServicePort(
                        name="service-port",
                        protocol="TCP",
                        port=req.internal_port,
                        target_port=req.internal_port,
                    )
                ],
            ),
        )
        service = self.gateway.create_service(service)
        expose = ServiceExpose(
            id=expose_id,
            sandbox_id=req.sandbox_id,
            name=req.name,
            protocol=req.protocol,
            internal_port=req.internal_port,
            service_name=service_name,
            status=ExposeStatus.PENDING,
            created_at=now,
            updated_at=now,
        )
        if req.protocol == ProtocolType.HTTP:
            domain = req.domain or f"{req.internal_port}-{req.sandbox_id}.{self.settings.sandbox.base_domain}"
            path = req.path or "/"
            ingress_name = f"ing-{expose_id}"
            ingress = client.V1Ingress(
                metadata=client.V1ObjectMeta(
                    name=ingress_name,
                    namespace=self.gateway.namespace,
                    labels={
                        "litterbox.io/expose-id": expose_id,
                        "litterbox.io/sandbox-id": req.sandbox_id,
                    },
                    annotations={
                        "traefik.ingress.kubernetes.io/router.entrypoints": "websecure",
                        "traefik.ingress.kubernetes.io/router.tls": "true",
                        "traefik.ingress.kubernetes.io/router.tls.certresolver": "letsencrypt",
                    },
                ),
                spec=client.V1IngressSpec(
                    ingress_class_name="traefik",
                    rules=[
                        client.V1IngressRule(
                            host=domain,
                            http=client.V1HTTPIngressRuleValue(
                                paths=[
                                    client.V1HTTPIngressPath(
                                        path=path,
                                        path_type="Prefix",
                                        backend=client.V1IngressBackend(
                                            service=client.V1IngressServiceBackend(
                                                name=service_name,
                                                port=client.V1ServiceBackendPort(number=req.internal_port),
                                            )
                                        ),
                                    )
                                ]
                            ),
                        )
                    ],
                ),
            )
            self.gateway.create_ingress(ingress)
            expose.external_url = f"https://{domain}{path}"
            expose.domain = domain
            expose.path = path
            expose.ingress_name = ingress_name
        else:
            service_port = service.spec.ports[0]
            expose.external_port = service_port.node_port or 0
            expose.external_ip = self._pick_node_ip()
        expose.status = ExposeStatus.READY
        expose.message = "Service exposed successfully"
        return expose

    def get_expose(self, expose_id: str) -> ServiceExpose:
        service = self.gateway.read_service(f"svc-{expose_id}")
        return self._service_to_expose(service)

    def list_exposes(self, sandbox_id: str) -> list[ServiceExpose]:
        services = self.gateway.list_services(f"litterbox.io/sandbox-id={sandbox_id}")
        return [self._service_to_expose(service) for service in services if (service.metadata.labels or {}).get("litterbox.io/expose-id")]

    def delete_expose(self, expose_id: str) -> None:
        self.gateway.delete_ingress(f"ing-{expose_id}")
        self.gateway.delete_service(f"svc-{expose_id}")

    def delete_exposes_for_sandbox(self, sandbox_id: str) -> None:
        """Delete all Service and Ingress resources owned by *sandbox_id*.

        Uses the ``litterbox.io/sandbox-id`` label selector so no knowledge of
        individual expose IDs is required by the caller.  Safe to call even
        when the sandbox has no exposes.
        """
        services = self.gateway.list_services(f"litterbox.io/sandbox-id={sandbox_id}")
        for svc in services:
            expose_id = (svc.metadata.labels or {}).get("litterbox.io/expose-id")
            if expose_id:
                self.gateway.delete_ingress(f"ing-{expose_id}")
            self.gateway.delete_service(svc.metadata.name)

    def _service_to_expose(self, service: client.V1Service) -> ServiceExpose:
        labels = service.metadata.labels or {}
        annotations = service.metadata.annotations or {}
        expose_id = labels["litterbox.io/expose-id"]
        protocol = ProtocolType(annotations.get("litterbox.io/protocol", "http"))
        created_at = annotations.get("litterbox.io/created-at") or utcnow().isoformat()
        expose = ServiceExpose(
            id=expose_id,
            sandbox_id=labels.get("litterbox.io/sandbox-id", ""),
            name=annotations.get("litterbox.io/name", ""),
            protocol=protocol,
            internal_port=int(annotations.get("litterbox.io/internal-port", service.spec.ports[0].port)),
            service_name=service.metadata.name,
            status=ExposeStatus.READY,
            message="Service exposed successfully",
            created_at=created_at,
            updated_at=utcnow(),
        )
        if protocol == ProtocolType.HTTP:
            try:
                ingress = self.gateway.read_ingress(f"ing-{expose_id}")
            except ApiException:
                return expose
            rule = ingress.spec.rules[0]
            path = rule.http.paths[0].path if rule.http and rule.http.paths else "/"
            expose.domain = rule.host or ""
            expose.path = path
            expose.ingress_name = ingress.metadata.name
            expose.external_url = f"https://{expose.domain}{path}"
        else:
            expose.external_port = service.spec.ports[0].node_port or 0
            expose.external_ip = self._pick_node_ip()
        return expose

    def _pick_node_ip(self) -> str:
        for node in self.gateway.list_nodes():
            for address in node.status.addresses or []:
                if address.type == "ExternalIP":
                    return address.address
            for address in node.status.addresses or []:
                if address.type == "InternalIP":
                    return address.address
        raise RuntimeError("no available node IP")
