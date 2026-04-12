from __future__ import annotations

from collections.abc import Iterable
from contextlib import suppress
from datetime import datetime
import json
import os
import threading
import time
from typing import Any

from kubernetes import client, config
from kubernetes.client import ApiException
from kubernetes.stream import stream

from orchestrator.config import Settings


class KubernetesGateway:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        kubeconfig = settings.kubernetes.kubeconfig
        if kubeconfig:
            config.load_kube_config(config_file=kubeconfig)
        else:
            with suppress(config.ConfigException):
                config.load_incluster_config()
            if not client.Configuration.get_default_copy().host:
                config.load_kube_config()

        self.core = self._build_core_api()
        self.apps = client.AppsV1Api(self._build_api_client())
        self.networking = client.NetworkingV1Api(self._build_api_client())
        self.namespace = settings.kubernetes.namespace
        self._lock = threading.Lock()
        self.available_runtime_classes = set()
        try:
            self.available_runtime_classes = set(self.read_runtime_classes())
        except Exception:  # noqa: BLE001
            self.available_runtime_classes = set()

    @staticmethod
    def _build_api_client() -> client.ApiClient:
        return client.ApiClient(client.Configuration.get_default_copy())

    @classmethod
    def _build_core_api(cls) -> client.CoreV1Api:
        return client.CoreV1Api(cls._build_api_client())

    def create_or_update_json_configmap(
        self,
        *,
        name: str,
        labels: dict[str, str],
        payload_key: str,
        payload: dict[str, Any],
        annotations: dict[str, str] | None = None,
    ) -> client.V1ConfigMap:
        body = client.V1ConfigMap(
            metadata=client.V1ObjectMeta(
                name=name,
                namespace=self.namespace,
                labels=labels,
                annotations=annotations or {},
            ),
            data={payload_key: json.dumps(payload, default=str)},
        )
        try:
            return self.core.create_namespaced_config_map(self.namespace, body)
        except ApiException as exc:
            if exc.status != 409:
                raise
        current = self.core.read_namespaced_config_map(name, self.namespace)
        current.data = {payload_key: json.dumps(payload, default=str)}
        current.metadata.labels = labels
        current.metadata.annotations = annotations or current.metadata.annotations
        return self.core.replace_namespaced_config_map(name, self.namespace, current)

    def get_json_configmap(self, name: str, payload_key: str) -> tuple[client.V1ConfigMap, dict[str, Any]]:
        cm = self.core.read_namespaced_config_map(name, self.namespace)
        payload = json.loads(cm.data[payload_key])
        return cm, payload

    def list_json_configmaps(
        self,
        *,
        label_selector: str,
        payload_key: str,
    ) -> list[tuple[client.V1ConfigMap, dict[str, Any]]]:
        result: list[tuple[client.V1ConfigMap, dict[str, Any]]] = []
        cms = self.core.list_namespaced_config_map(self.namespace, label_selector=label_selector)
        for cm in cms.items:
            raw = cm.data.get(payload_key)
            if raw is None:
                continue
            result.append((cm, json.loads(raw)))
        return result

    def delete_configmap(self, name: str) -> None:
        try:
            self.core.delete_namespaced_config_map(name, self.namespace)
        except ApiException as exc:
            if exc.status != 404:
                raise

    def create_deployment(self, deployment: client.V1Deployment) -> client.V1Deployment:
        return self.apps.create_namespaced_deployment(self.namespace, deployment)

    def read_deployment(self, name: str) -> client.V1Deployment:
        return self.apps.read_namespaced_deployment(name, self.namespace)

    def patch_deployment(self, name: str, body: dict[str, Any]) -> client.V1Deployment:
        return self.apps.patch_namespaced_deployment(name, self.namespace, body)

    def replace_deployment(self, deployment: client.V1Deployment) -> client.V1Deployment:
        return self.apps.replace_namespaced_deployment(deployment.metadata.name, self.namespace, deployment)

    def list_deployments(self, label_selector: str = "") -> list[client.V1Deployment]:
        return self.apps.list_namespaced_deployment(self.namespace, label_selector=label_selector).items

    def delete_deployment(self, name: str, grace_period_seconds: int = 0) -> None:
        body = client.V1DeleteOptions(
            grace_period_seconds=grace_period_seconds,
            propagation_policy="Foreground",
        )
        try:
            self.apps.delete_namespaced_deployment(name, self.namespace, body=body)
        except ApiException as exc:
            if exc.status != 404:
                raise

    def scale_deployment(self, name: str, replicas: int) -> client.V1Deployment:
        return self.patch_deployment(name, {"spec": {"replicas": replicas}})

    def list_pods(self, label_selector: str) -> list[client.V1Pod]:
        return self.core.list_namespaced_pod(self.namespace, label_selector=label_selector).items

    def delete_pod(self, name: str, grace_period_seconds: int = 0) -> None:
        body = client.V1DeleteOptions(grace_period_seconds=grace_period_seconds)
        self.core.delete_namespaced_pod(name, self.namespace, body=body)

    def wait_for_pod_ready(self, label_selector: str, timeout_seconds: int = 120) -> client.V1Pod:
        deadline = time.time() + timeout_seconds
        last_error: str | None = None
        while time.time() < deadline:
            for pod in self.list_pods(label_selector):
                if pod.metadata.deletion_timestamp is not None:
                    continue
                if pod.status.phase != "Running":
                    last_error = pod.status.phase
                    continue
                statuses = pod.status.container_statuses or []
                if statuses and all(status.ready for status in statuses):
                    return pod
            time.sleep(1)
        raise TimeoutError(f"timed out waiting for pod ready: {label_selector} ({last_error})")

    def get_first_running_pod(self, sandbox_id: str) -> client.V1Pod:
        for pod in self.list_pods(f"app={sandbox_id},component=sandbox"):
            if pod.status.phase == "Running":
                return pod
        raise RuntimeError(f"no running pods found for sandbox {sandbox_id}")

    @staticmethod
    def _container_name(pod: client.V1Pod) -> str | None:
        containers = pod.spec.containers or []
        if len(containers) <= 1:
            return None
        return containers[0].name

    def _exec_stream(self, pod: client.V1Pod, *, command: list[str], stdin: bool, tty: bool):
        kwargs = {
            "command": command,
            "stderr": True,
            "stdin": stdin,
            "stdout": True,
            "tty": tty,
            "_preload_content": False,
        }
        if container_name := self._container_name(pod):
            kwargs["container"] = container_name
        # `stream()` swaps the bound ApiClient request handler to websocket mode.
        # Keep exec/terminal traffic on a dedicated CoreV1Api so regular queries
        # on `self.core` continue to use the normal HTTP transport.
        exec_core = self._build_core_api()
        return stream(
            exec_core.connect_get_namespaced_pod_exec,
            pod.metadata.name,
            self.namespace,
            **kwargs,
        )

    @staticmethod
    def _collect_exec_response(response, timeout_seconds: int) -> tuple[str, str]:
        deadline = time.time() + timeout_seconds
        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        while response.is_open():
            response.update(timeout=1)
            if response.peek_stdout():
                stdout_parts.append(response.read_stdout())
            if response.peek_stderr():
                stderr_parts.append(response.read_stderr())
            if time.time() > deadline:
                response.close()
                raise TimeoutError(f"exec timed out after {timeout_seconds}s")
        response.close()
        return "".join(stdout_parts), "".join(stderr_parts)

    def exec_command(
        self,
        sandbox_id: str,
        command: list[str],
        tty: bool = False,
        timeout_seconds: int = 60,
    ) -> tuple[str, str]:
        pod = self.get_first_running_pod(sandbox_id)
        response = self._exec_stream(pod, command=command, stdin=False, tty=tty)
        return self._collect_exec_response(response, timeout_seconds)

    def exec_shell(self, sandbox_id: str, script: str, timeout_seconds: int = 60) -> tuple[str, str]:
        return self.exec_command(
            sandbox_id,
            ["/bin/sh", "-lc", script],
            timeout_seconds=timeout_seconds,
        )

    def open_shell(self, sandbox_id: str):
        pod = self.get_first_running_pod(sandbox_id)
        return self._exec_stream(
            pod,
            command=[
                "/bin/sh",
                "-lc",
                "if command -v bash >/dev/null 2>&1; then exec bash -il; else exec sh -il; fi",
            ],
            stdin=True,
            tty=True,
        )

    def open_acp(self, sandbox_id: str):
        pod = self.get_first_running_pod(sandbox_id)
        return self._exec_stream(
            pod,
            command=[
                "/bin/sh",
                "-lc",
                (
                    "cd /workspace || exit 1; "
                    "if command -v claude-agent-acp >/dev/null 2>&1; then "
                    "exec claude-agent-acp; "
                    "elif command -v claude-code-acp >/dev/null 2>&1; then "
                    "exec claude-code-acp; "
                    "else "
                    "echo 'acp binary not found: claude-agent-acp/claude-code-acp' >&2; "
                    "exit 127; "
                    "fi"
                ),
            ],
            stdin=True,
            tty=False,
        )

    def create_service(self, service: client.V1Service) -> client.V1Service:
        return self.core.create_namespaced_service(self.namespace, service)

    def read_service(self, name: str) -> client.V1Service:
        return self.core.read_namespaced_service(name, self.namespace)

    def list_services(self, label_selector: str = "") -> list[client.V1Service]:
        return self.core.list_namespaced_service(self.namespace, label_selector=label_selector).items

    def delete_service(self, name: str) -> None:
        try:
            self.core.delete_namespaced_service(name, self.namespace)
        except ApiException as exc:
            if exc.status != 404:
                raise

    def create_ingress(self, ingress: client.V1Ingress) -> client.V1Ingress:
        return self.networking.create_namespaced_ingress(self.namespace, ingress)

    def read_ingress(self, name: str) -> client.V1Ingress:
        return self.networking.read_namespaced_ingress(name, self.namespace)

    def delete_ingress(self, name: str) -> None:
        try:
            self.networking.delete_namespaced_ingress(name, self.namespace)
        except ApiException as exc:
            if exc.status != 404:
                raise

    def list_nodes(self) -> list[client.V1Node]:
        return self.core.list_node(limit=10).items

    def read_runtime_classes(self) -> list[str]:
        api = client.NodeV1Api()
        return [item.metadata.name for item in api.list_runtime_class().items]

    def secret_exists(self, name: str) -> bool:
        if not name:
            return False
        try:
            self.core.read_namespaced_secret(name, self.namespace)
            return True
        except ApiException as exc:
            if exc.status == 404:
                return False
            raise

    def cleanup_named_resources(self, names: Iterable[str]) -> None:
        for name in names:
            self.delete_configmap(name)

    @staticmethod
    def timestamp(value: datetime | None) -> str | None:
        return value.isoformat() if value else None
