#!/usr/bin/env python3
"""End-to-end test for the CRD-backed sandbox lifecycle.

The script drives the official E2B SDK through the orchestrator and asserts the
controller-written Kubernetes state. Run it against a cluster where the
sandbox-controller and orchestrator (with sandbox.backend=crd) are deployed.

Environment:
  API_URL             orchestrator URL              (default http://127.0.0.1:8080)
  E2B_API_KEY         E2B API key                   (default local-e2b-key)
  E2B_DOMAIN          E2B data-plane domain         (default localhost)
  USE_HOST_ROUTING    use 49983-<id>.<domain> instead of the path proxy
                      (default: enabled when E2B_DOMAIN is not localhost)
  LITTERBOX_API_TOKEN bearer token for /api/v1 calls (defaults to E2B_API_KEY)
  K8S_NAMESPACE       namespace for sandboxes       (default default)
  TEMPLATE_ID         template / cleanup prefix     (default crd-e2e-<random>)
  SANDBOX_IMAGE       sandbox image                 (default ubuntu:22.04)
  KUBECONFIG          kubeconfig, if not in-cluster

Requires: e2b, httpx, kubernetes (all available in the orchestrator venv, and
e2b can be added with ``uv run --with e2b==2.46.0``).
"""

from __future__ import annotations

import os
import random
import string
import sys
import time

import httpx
from e2b import Sandbox
from kubernetes import client, config
from kubernetes.client import ApiException


API_URL = os.environ.get("API_URL", "http://127.0.0.1:8080").rstrip("/")
E2B_API_KEY = os.environ.get("E2B_API_KEY", "local-e2b-key")
E2B_DOMAIN = os.environ.get("E2B_DOMAIN", "localhost")
USE_HOST_ROUTING = os.environ.get(
    "USE_HOST_ROUTING",
    "1" if E2B_DOMAIN not in {"localhost", "127.0.0.1"} else "0",
).lower() in {"1", "true", "yes"}
API_TOKEN = os.environ.get("LITTERBOX_API_TOKEN", E2B_API_KEY)
NAMESPACE = os.environ.get("K8S_NAMESPACE", "default")
TEMPLATE_ID = os.environ.get(
    "TEMPLATE_ID", "crd-e2e-" + "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
)
SANDBOX_IMAGE = os.environ.get("SANDBOX_IMAGE", "ubuntu:22.04")
CRD_GROUP = "litterbox.io"
CRD_VERSION = "v1alpha1"
CRD_PLURAL = "sandboxes"
E2B_HEADERS = {"X-API-Key": E2B_API_KEY}
AUTH_HEADERS = {"Authorization": f"Bearer {API_TOKEN}"}


def log(message: str) -> None:
    print(f"[e2e] {message}", flush=True)


def wait_until(description: str, predicate, *, timeout: float = 120, interval: float = 1.0):
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            result = predicate()
            if result:
                return result
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        time.sleep(interval)
    suffix = f" (last error: {last_error})" if last_error else ""
    raise TimeoutError(f"timed out waiting for {description}{suffix}")


def load_clients():
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config(config_file=os.environ.get("KUBECONFIG") or None)
    api_client = client.ApiClient()
    return (
        client.CustomObjectsApi(api_client),
        client.CoreV1Api(api_client),
        api_client,
    )


CRD_API, CORE_API, API_CLIENT = load_clients()


def get_cr(sandbox_id: str):
    return CRD_API.get_namespaced_custom_object(
        CRD_GROUP, CRD_VERSION, NAMESPACE, CRD_PLURAL, sandbox_id
    )


def cr_phase(sandbox_id: str) -> str:
    return (get_cr(sandbox_id).get("status") or {}).get("phase", "")


def pod_exists(sandbox_id: str) -> bool:
    try:
        pod = CORE_API.read_namespaced_pod(sandbox_id, NAMESPACE)
    except ApiException as exc:
        if exc.status == 404:
            return False
        raise
    return pod.metadata.deletion_timestamp is None


def pvc_exists(name: str) -> bool:
    try:
        CORE_API.read_namespaced_persistent_volume_claim(name, NAMESPACE)
        return True
    except ApiException as exc:
        if exc.status == 404:
            return False
        raise


def create_template() -> None:
    payload = {
        "id": TEMPLATE_ID,
        "name": TEMPLATE_ID,
        "description": "CRD backend e2e",
        "image": SANDBOX_IMAGE,
        "command": "sleep infinity",
        "cpu_millicores": 500,
        "memory_mb": 512,
        "ttl_seconds": 600,
        "workspace": {"enabled": True, "size": "1Gi"},
    }
    response = httpx.post(
        f"{API_URL}/api/v1/templates", json=payload, headers=AUTH_HEADERS, timeout=30
    )
    if response.status_code == 409:
        log(f"template {TEMPLATE_ID} already exists")
        return
    response.raise_for_status()
    log(f"template created: {TEMPLATE_ID}")


def cleanup() -> None:
    with httpx.Client(timeout=20) as http:
        http.delete(f"{API_URL}/api/v1/templates/{TEMPLATE_ID}", headers=AUTH_HEADERS)
    try:
        leftovers = CRD_API.list_namespaced_custom_object(
            CRD_GROUP,
            CRD_VERSION,
            NAMESPACE,
            CRD_PLURAL,
            label_selector=f"litterbox.io/template-id={TEMPLATE_ID}",
        )
    except ApiException:
        leftovers = {"items": []}
    for item in leftovers.get("items", []):
        name = item["metadata"]["name"]
        log(f"cleaning leftover sandbox {name}")
        try:
            CRD_API.delete_namespaced_custom_object(
                CRD_GROUP, CRD_VERSION, NAMESPACE, CRD_PLURAL, name
            )
        except ApiException:
            pass
        try:
            CORE_API.delete_namespaced_persistent_volume_claim(f"workspace-{name}", NAMESPACE)
        except ApiException:
            pass


def gate_envd(data_url: str) -> None:
    headers = E2B_HEADERS if USE_HOST_ROUTING else AUTH_HEADERS

    def attempt():
        response = httpx.post(
            f"{data_url}/v1/workspace/restore", json={}, headers=headers, timeout=30
        )
        if response.status_code in {409, 502, 503}:
            return None
        response.raise_for_status()
        return True

    wait_until("envd workspace gate", attempt, timeout=60)


def connect_sandbox(sandbox_id: str) -> tuple[Sandbox, str]:
    path_url = f"{API_URL}/api/v1/sandboxes/{sandbox_id}/envd"
    data_url = (
        f"https://49983-{sandbox_id}.{E2B_DOMAIN}" if USE_HOST_ROUTING else path_url
    )

    def attempt():
        try:
            return Sandbox.connect(
                sandbox_id,
                sandbox_url=data_url,
                api_url=f"{API_URL}/e2b",
                api_key=E2B_API_KEY,
                domain=E2B_DOMAIN,
                request_timeout=60,
            )
        except Exception as exc:  # noqa: BLE001
            log(f"connect retry: {exc}")
            return None

    sandbox = wait_until("E2B connect", attempt, timeout=180, interval=2)
    gate_envd(data_url)
    return sandbox, data_url


def assert_running(sandbox_id: str) -> dict:
    return wait_until(
        f"sandbox {sandbox_id} Running",
        lambda: (cr := get_cr(sandbox_id)) and cr.get("status", {}).get("phase") == "Running" and cr,
    )


def main() -> int:
    log(f"API {API_URL}, namespace {NAMESPACE}, template {TEMPLATE_ID}")
    cleanup()
    create_template()

    log("creating sandbox via E2B SDK")
    sandbox = Sandbox.create(
        template=TEMPLATE_ID,
        timeout=600,
        api_url=f"{API_URL}/e2b",
        api_key=E2B_API_KEY,
        domain=E2B_DOMAIN,
        request_timeout=60,
    )
    sandbox_id = sandbox.sandbox_id
    log(f"sandbox_id: {sandbox_id}")

    sandbox, data_url = connect_sandbox(sandbox_id)
    cr = assert_running(sandbox_id)
    spec = cr["spec"]
    assert spec["state"] == "Running", spec
    assert spec["image"] == SANDBOX_IMAGE, spec
    assert cr["status"]["podIP"], cr
    pod = CORE_API.read_namespaced_pod(sandbox_id, NAMESPACE)
    assert pod.metadata.labels["component"] == "sandbox"
    assert pod.metadata.labels["litterbox.io/sandbox-id"] == sandbox_id
    assert pvc_exists(f"workspace-{sandbox_id}")
    log(f"CR + Pod + PVC ready (podIP {cr['status']['podIP']})")

    result = sandbox.commands.run("uname -s && whoami")
    assert result.exit_code == 0, result
    assert "Linux" in result.stdout, result.stdout
    log(f"exec: {result.stdout.strip().splitlines()[0]}")

    sandbox.files.write("/workspace/e2e.txt", "hello from the CRD backend\n")
    assert sandbox.files.read("/workspace/e2e.txt") == "hello from the CRD backend\n"
    entries = sandbox.files.list("/workspace")
    assert any(entry.name == "e2e.txt" for entry in entries)
    log("file write/read/list OK")

    log("deleting the Pod to prove controller self-healing")
    CORE_API.delete_namespaced_pod(sandbox_id, NAMESPACE, grace_period_seconds=0)
    new_cr = wait_until(
        "Pod recreated and sandbox Running",
        lambda: (
            lambda current: current
            if current.get("status", {}).get("phase") == "Running"
            and current.get("status", {}).get("podIP")
            and pod_exists(sandbox_id)
            else None
        )(get_cr(sandbox_id)),
        timeout=180,
    )
    new_pod = CORE_API.read_namespaced_pod(sandbox_id, NAMESPACE)
    assert new_pod.metadata.uid != pod.metadata.uid
    log(f"Pod recreated by controller (new UID, podIP {new_cr['status']['podIP']})")

    # A recreated Pod also starts a fresh envd process, so the workspace gate
    # has to be opened again before data-plane calls succeed.
    gate_envd(data_url)

    # The envd proxy caches Pod IPs for a few seconds; retry until it refreshes.
    wait_until(
        "exec after Pod recreation",
        lambda: sandbox.commands.run("true").exit_code == 0,
        timeout=60,
    )
    log("exec works after self-healing")

    log("pausing through the E2B control plane")
    pause = httpx.post(
        f"{API_URL}/e2b/sandboxes/{sandbox_id}/pause",
        json={"memory": False},
        headers=E2B_HEADERS,
        timeout=30,
    )
    pause.raise_for_status()
    wait_until(
        "sandbox paused",
        lambda: cr_phase(sandbox_id) == "Paused" and not pod_exists(sandbox_id),
    )
    assert pvc_exists(f"workspace-{sandbox_id}")
    log("paused: Pod gone, workspace PVC retained")

    log("resuming and checking workspace persistence")
    sandbox, data_url = connect_sandbox(sandbox_id)
    assert_running(sandbox_id)
    assert sandbox.files.read("/workspace/e2e.txt") == "hello from the CRD backend\n"
    log("workspace survived pause/resume")

    log("setting a 5s TTL to prove controller-driven expiry")
    timeout = httpx.post(
        f"{API_URL}/e2b/sandboxes/{sandbox_id}/timeout",
        json={"timeout": 5},
        headers=E2B_HEADERS,
        timeout=30,
    )
    timeout.raise_for_status()
    wait_until(
        "TTL expiry paused the sandbox",
        lambda: cr_phase(sandbox_id) == "Paused" and not pod_exists(sandbox_id),
        timeout=60,
        interval=1.0,
    )
    cr = get_cr(sandbox_id)
    assert cr["spec"]["state"] == "Running", "controller must not rewrite spec.state"
    assert cr["status"]["pausedReason"] == "TTLExpired", cr["status"]
    log("TTL expiry paused the sandbox without deleting the PVC")

    log("resuming after TTL expiry")
    sandbox, data_url = connect_sandbox(sandbox_id)
    assert_running(sandbox_id)
    assert sandbox.files.read("/workspace/e2e.txt") == "hello from the CRD backend\n"
    log("workspace still intact after TTL resume")

    log("killing the sandbox")
    sandbox.kill()
    wait_until(
        "sandbox CR and PVC deleted",
        lambda: not cr_exists(sandbox_id) and not pvc_exists(f"workspace-{sandbox_id}") and not pod_exists(sandbox_id),
        timeout=120,
    )
    log("kill removed CR, Pod and PVC")

    cleanup()
    log("E2E PASS")
    return 0


def cr_exists(sandbox_id: str) -> bool:
    try:
        get_cr(sandbox_id)
        return True
    except ApiException as exc:
        if exc.status == 404:
            return False
        raise


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"[e2e] FAILED: {exc}", file=sys.stderr, flush=True)
        raise
