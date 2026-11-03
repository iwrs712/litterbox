#!/usr/bin/env python3
"""End-to-end test for the SandboxPool CRD + controller.

Verifies:
  - pool provisioning of warm Sandbox CRs
  - optimistic (resourceVersion) claim on allocation
  - ownerReference detachment for allocated sandboxes
  - automatic replenishment after a claim
  - deleting the pool removes warm sandboxes but keeps the allocated one

Environment:
  API_URL             orchestrator URL              (default http://127.0.0.1:8080)
  LITTERBOX_API_TOKEN bearer token for /api/v1      (required on authenticated installs)
  K8S_NAMESPACE       namespace for sandboxes       (default default)
  TEMPLATE_ID         template / cleanup prefix     (default pool-e2e-<random>)
  SANDBOX_IMAGE       sandbox image                 (required, e.g. the sandbox-agent image)
  KUBECONFIG          kubeconfig, if not in-cluster
"""

from __future__ import annotations

import os
import random
import string
import sys
import time

import httpx
from kubernetes import client, config
from kubernetes.client import ApiException


API_URL = os.environ.get("API_URL", "http://127.0.0.1:8080").rstrip("/")
API_TOKEN = os.environ.get("LITTERBOX_API_TOKEN", "")
NAMESPACE = os.environ.get("K8S_NAMESPACE", "default")
TEMPLATE_ID = os.environ.get(
    "TEMPLATE_ID", "pool-e2e-" + "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
)
SANDBOX_IMAGE = os.environ.get("SANDBOX_IMAGE", "")
GROUP = "litterbox.io"
VERSION = "v1alpha1"
HEADERS = {"Authorization": f"Bearer {API_TOKEN}"} if API_TOKEN else {}


def log(message: str) -> None:
    print(f"[pool-e2e] {message}", flush=True)


def wait_until(description: str, predicate, *, timeout: float = 240, interval: float = 1.0):
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
    return client.CustomObjectsApi(api_client), client.CoreV1Api(api_client)


CRD_API, CORE_API = load_clients()


def api_get(path: str):
    response = httpx.get(f"{API_URL}{path}", headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.json()["data"]


def api_post(path: str, payload: dict, expected: int = 200):
    response = httpx.post(f"{API_URL}{path}", json=payload, headers=HEADERS, timeout=180)
    if response.status_code != expected:
        raise RuntimeError(f"POST {path} -> {response.status_code}: {response.text}")
    return response.json().get("data") if response.content else None


def api_delete(path: str) -> None:
    response = httpx.delete(f"{API_URL}{path}", headers=HEADERS, timeout=60)
    if response.status_code not in {200, 204, 404}:
        raise RuntimeError(f"DELETE {path} -> {response.status_code}: {response.text}")


def list_sandbox_crs(selector: str) -> list[dict]:
    result = CRD_API.list_namespaced_custom_object(
        GROUP, VERSION, NAMESPACE, "sandboxes", label_selector=selector
    )
    return result.get("items", [])


def get_sandbox_cr(sandbox_id: str) -> dict:
    return CRD_API.get_namespaced_custom_object(
        GROUP, VERSION, NAMESPACE, "sandboxes", sandbox_id
    )


def cr_exists(kind: str, name: str) -> bool:
    try:
        CRD_API.get_namespaced_custom_object(GROUP, VERSION, NAMESPACE, kind, name)
        return True
    except ApiException as exc:
        if exc.status == 404:
            return False
        raise


def pod_exists(sandbox_id: str) -> bool:
    try:
        pod = CORE_API.read_namespaced_pod(sandbox_id, NAMESPACE)
    except ApiException as exc:
        if exc.status == 404:
            return False
        raise
    return pod.metadata.deletion_timestamp is None


def pvc_exists(sandbox_id: str) -> bool:
    try:
        CORE_API.read_namespaced_persistent_volume_claim(f"workspace-{sandbox_id}", NAMESPACE)
        return True
    except ApiException as exc:
        if exc.status == 404:
            return False
        raise


def cleanup() -> None:
    try:
        api_delete(f"/api/v1/pools/{TEMPLATE_ID}")
    except Exception:
        pass
    for item in list_sandbox_crs(f"litterbox.io/template-id={TEMPLATE_ID}"):
        name = item["metadata"]["name"]
        try:
            CRD_API.delete_namespaced_custom_object(
                GROUP, VERSION, NAMESPACE, "sandboxes", name
            )
        except ApiException:
            pass
    try:
        api_delete(f"/api/v1/templates/{TEMPLATE_ID}")
    except Exception:
        pass


def main() -> int:
    if not SANDBOX_IMAGE:
        raise SystemExit("SANDBOX_IMAGE is required")
    log(f"API {API_URL}, namespace {NAMESPACE}, template {TEMPLATE_ID}")
    cleanup()

    api_post(
        "/api/v1/templates",
        {
            "id": TEMPLATE_ID,
            "name": TEMPLATE_ID,
            "description": "SandboxPool E2E",
            "image": SANDBOX_IMAGE,
            "command": "sleep infinity",
            "cpu_millicores": 500,
            "memory_mb": 512,
            "ttl_seconds": 600,
            "workspace": {"enabled": True, "size": "1Gi"},
        },
        expected=201,
    )
    log("template created")

    api_post(
        f"/api/v1/pools/{TEMPLATE_ID}",
        {"min_ready": 1, "target_ready": 1, "max_creating": 2},
        expected=201,
    )
    pool = wait_until(
        "pool ready >= 1",
        lambda: (lambda status: status if status["ready"] >= 1 else None)(
            api_get(f"/api/v1/pools/{TEMPLATE_ID}")
        ),
    )
    log(f"pool ready (ready={pool['ready']}, creating={pool['creating']})")

    warm = wait_until(
        "one available pool sandbox",
        lambda: (lambda items: items[0] if len(items) == 1 else None)(
            list_sandbox_crs(
                f"litterbox.io/pool={TEMPLATE_ID},litterbox.io/pool-state=available"
            )
        ),
    )
    warm_id = warm["metadata"]["name"]
    assert warm["spec"].get("ttlSeconds", 0) == 0
    assert any(
        ref.get("kind") == "SandboxPool" for ref in warm["metadata"].get("ownerReferences", [])
    ), "warm sandbox must be owned by the pool"
    log(f"warm sandbox {warm_id} is available and owned by the pool")

    allocated = api_post(
        "/api/v1/sandboxes",
        {"template_id": TEMPLATE_ID, "metadata": {"e2e": "pool"}},
        expected=201,
    )
    assert allocated["id"] == warm_id, (allocated["id"], warm_id)
    assert allocated["pool_state"] == "allocated", allocated
    log(f"claimed warm sandbox {warm_id} via optimistic patch")

    claimed = get_sandbox_cr(warm_id)
    assert claimed["metadata"]["labels"]["litterbox.io/pool-state"] == "allocated"
    assert claimed["metadata"].get("ownerReferences") in (None, []), claimed["metadata"]
    assert claimed["spec"]["ttlSeconds"] == 600
    assert claimed["spec"].get("ttlAnchor")
    wait_until(
        "allocated sandbox Running",
        lambda: get_sandbox_cr(warm_id).get("status", {}).get("phase") == "Running",
    )
    assert pod_exists(warm_id)
    assert pvc_exists(warm_id)
    log("allocated sandbox is Running with Pod + PVC")

    replenished = wait_until(
        "pool replenished with a new warm sandbox",
        lambda: (lambda items: items[0] if items else None)(
            [
                item
                for item in list_sandbox_crs(
                    f"litterbox.io/pool={TEMPLATE_ID},litterbox.io/pool-state=available"
                )
                if item["metadata"]["name"] != warm_id
            ]
        ),
    )
    log(f"pool replenished with {replenished['metadata']['name']}")
    pool = wait_until(
        "pool status allocated=1, ready=1",
        lambda: (lambda status: status if status["allocated"] >= 1 and status["ready"] >= 1 else None)(
            api_get(f"/api/v1/pools/{TEMPLATE_ID}")
        ),
    )
    log(f"pool status: ready={pool['ready']} allocated={pool['allocated']}")

    log("deleting the pool; warm sandboxes should be GC'd, allocated must survive")
    api_delete(f"/api/v1/pools/{TEMPLATE_ID}")
    wait_until(
        "pool CR removed and warm sandboxes gone",
        lambda: not cr_exists("sandboxpools", TEMPLATE_ID)
        and not list_sandbox_crs(f"litterbox.io/pool={TEMPLATE_ID},litterbox.io/pool-state=available"),
    )
    assert cr_exists("sandboxes", warm_id), "allocated sandbox must survive pool deletion"
    assert get_sandbox_cr(warm_id).get("status", {}).get("phase") == "Running"
    assert pod_exists(warm_id)
    log("allocated sandbox survived pool deletion and is still Running")

    log("killing the allocated sandbox")
    api_delete(f"/api/v1/sandboxes/{warm_id}")
    wait_until(
        "allocated sandbox CR, Pod and PVC removed",
        lambda: not cr_exists("sandboxes", warm_id)
        and not pod_exists(warm_id)
        and not pvc_exists(warm_id),
    )
    log("allocated sandbox cleaned up")

    cleanup()
    log("POOL E2E PASS")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"[pool-e2e] FAILED: {exc}", file=sys.stderr, flush=True)
        raise
