from __future__ import annotations

from collections import defaultdict
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from orchestrator.main import app
from orchestrator.worker_profiles import queue_for_worker


def wait_until(predicate, timeout: float = 120, interval: float = 1.0):
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            result = predicate()
            if result:
                return result
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        time.sleep(interval)
    if last_error:
        raise last_error
    raise TimeoutError("condition not met in time")


def wait_for_process_ready(log_path: Path, timeout: float = 30) -> None:
    wait_until(lambda: log_path.exists() and "ready" in log_path.read_text(errors="ignore").lower(), timeout=timeout, interval=0.5)


def start_celery_process(root: Path, name: str, *args: str) -> tuple[subprocess.Popen[str], Path]:
    log_dir = root / ".pytest-celery"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"{name}.log"
    log_file = log_path.open("w")
    process = subprocess.Popen(
        [sys.executable, "-m", "celery", "-A", "orchestrator.celery_app:celery_app", *args],
        cwd=root,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
    )
    process.log_file = log_file
    return process, log_path


def start_python_process(root: Path, name: str, *args: str) -> tuple[subprocess.Popen[str], Path]:
    log_dir = root / ".pytest-celery"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"{name}.log"
    log_file = log_path.open("w")
    process = subprocess.Popen(
        [sys.executable, *args],
        cwd=root,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
    )
    process.log_file = log_file
    return process, log_path


@pytest.fixture(scope="module", autouse=True)
def celery_runtime():
    root = Path(__file__).resolve().parents[2]
    broker_queue = "orchestrator:ttl"
    subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from redis import Redis; "
                "Redis(host='127.0.0.1', port=3379, password='difyai123456', db=2)"
                f".delete('{broker_queue}')"
            ),
        ],
        cwd=root,
        check=True,
    )
    processes: list[subprocess.Popen[str]] = []
    try:
        ttl_worker, ttl_log = start_python_process(
            root,
            "ttl-worker",
            "-m",
            "orchestrator.worker_runner",
            "ttl",
        )
        processes.append(ttl_worker)
        wait_for_process_ready(ttl_log)
        webhook_worker, webhook_log = start_celery_process(
            root,
            "webhook-worker",
            "worker",
            "-P",
            "solo",
            "-l",
            "info",
            "-Q",
            queue_for_worker("webhook"),
            "-n",
            "webhook-test@%h",
        )
        processes.append(webhook_worker)
        wait_for_process_ready(webhook_log)
        pool_worker, pool_log = start_celery_process(
            root,
            "pool-worker",
            "worker",
            "-P",
            "solo",
            "-l",
            "info",
            "-Q",
            queue_for_worker("pool"),
            "-n",
            "pool-test@%h",
        )
        processes.append(pool_worker)
        wait_for_process_ready(pool_log)
        time.sleep(2)
        yield
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            log_file = getattr(process, "log_file", None)
            if log_file:
                log_file.close()


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def tracker(client):
    prefix = f"it-{uuid4().hex[:8]}"
    data = defaultdict(list)
    data["prefix"] = prefix
    data["tenant_id"] = f"{prefix}-tenant"
    data["user_id"] = f"{prefix}-user"
    yield data
    container = client.app.state.container
    for expose_id in reversed(data["exposes"]):
        try:
            container.expose_service.delete_expose(expose_id)
        except Exception:
            pass
    for sandbox_id in reversed(data["sandboxes"]):
        try:
            container.sandbox_service.delete_sandbox(sandbox_id)
        except Exception:
            pass
    for template_id in reversed(data["pools"]):
        try:
            container.pool_service.delete_pool(template_id)
        except Exception:
            pass
    for webhook_id in reversed(data["webhooks"]):
        try:
            container.webhook_service.delete_webhook(webhook_id)
        except Exception:
            pass
    for template_id in reversed(data["templates"]):
        try:
            container.template_service.delete_template(template_id)
        except Exception:
            pass


@pytest.fixture(scope="module")
def base_template_payload(tracker):
    return {
        "id": f"{tracker['prefix']}-tpl",
        "name": f"{tracker['prefix']}-template",
        "description": "integration template",
        "image": "alpine:3.19",
        "command": "sleep 3600",
        "cpu_millicores": 500,
        "memory_mb": 512,
        "metadata": {
            "user_id": tracker["user_id"],
            "tenant_id": tracker["tenant_id"],
        },
    }


@pytest.fixture(scope="module")
def created_template(client, tracker, base_template_payload):
    response = client.post("/api/v1/templates", json=base_template_payload)
    assert response.status_code == 201, response.text
    assert "disk_gb" not in response.json()["data"]
    template_id = response.json()["data"]["id"]
    tracker["templates"].append(template_id)
    return template_id


@pytest.fixture(scope="module")
def created_sandbox(client, tracker, created_template):
    response = client.post(
        "/api/v1/sandboxes",
        json={
            "name": f"{tracker['prefix']}-sandbox",
            "template_id": created_template,
            "metadata": {
                "user_id": tracker["user_id"],
                "tenant_id": tracker["tenant_id"],
                "project_id": f"{tracker['prefix']}-project",
            },
        },
    )
    assert response.status_code == 201, response.text
    assert "workspace_path" not in response.json()["data"]
    sandbox_id = response.json()["data"]["id"]
    tracker["sandboxes"].append(sandbox_id)
    wait_until(lambda: client.get(f"/api/v1/sandboxes/{sandbox_id}").json()["data"]["status"] == "running")
    return sandbox_id


@pytest.fixture(scope="module")
def created_pool(client, tracker):
    template_id = f"{tracker['prefix']}-pooltpl"
    response = client.post(
        "/api/v1/templates",
        json={
            "id": template_id,
            "name": f"{tracker['prefix']}-pool-template",
            "description": "pool template",
            "image": "alpine:3.19",
            "command": "sleep 3600",
            "cpu_millicores": 500,
            "memory_mb": 512,
            "metadata": {"user_id": tracker["user_id"], "tenant_id": tracker["tenant_id"]},
        },
    )
    assert response.status_code == 201, response.text
    tracker["templates"].append(template_id)
    response = client.post(
        f"/api/v1/pools/{template_id}",
        json={"min_ready": 1},
    )
    assert response.status_code == 201, response.text
    tracker["pools"].append(template_id)
    wait_until(
        lambda: client.get(f"/api/v1/pools/{template_id}").json()["data"]["ready"] >= 1,
        timeout=180,
    )
    return template_id


@pytest.fixture(scope="module")
def webhook_receiver():
    received: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers["Content-Length"])
            received.append(json.loads(self.rfile.read(length)))
            self.send_response(200)
            self.end_headers()

        def log_message(self, format, *args):  # noqa: A003
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, received
    server.shutdown()
    thread.join(timeout=2)


@pytest.fixture(scope="module")
def created_webhook(client, tracker, webhook_receiver):
    server, _ = webhook_receiver
    response = client.post(
        "/api/v1/webhooks",
        json={
            "id": f"{tracker['prefix']}-webhook",
            "name": "integration-webhook",
            "user_id": tracker["user_id"],
            "url": f"http://127.0.0.1:{server.server_port}/hook",
            "events": ["sandbox_started", "sandbox_ready", "sandbox_deleted"],
        },
    )
    assert response.status_code == 201, response.text
    webhook_id = response.json()["data"]["id"]
    tracker["webhooks"].append(webhook_id)
    return webhook_id


def test_root_and_health(client):
    root = client.get("/")
    assert root.status_code == 200
    assert root.json()["message"] == "Litterbox API is running"

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["success"] is True


def test_create_template_endpoint(created_template, base_template_payload):
    assert created_template == base_template_payload["id"]


def test_get_template_endpoint(client, created_template):
    response = client.get(f"/api/v1/templates/{created_template}")
    assert response.status_code == 200
    assert response.json()["data"]["id"] == created_template
    assert "disk_gb" not in response.json()["data"]


def test_list_templates_endpoint(client, tracker, created_template):
    response = client.get("/api/v1/templates", params={"name": tracker["prefix"]})
    assert response.status_code == 200
    ids = [item["id"] for item in response.json()["data"]["templates"]]
    assert created_template in ids


def test_update_template_endpoint(client, created_template):
    response = client.patch(
        f"/api/v1/templates/{created_template}",
        json={"description": "updated description", "memory_mb": 768},
    )
    assert response.status_code == 200
    assert response.json()["data"]["description"] == "updated description"
    assert response.json()["data"]["memory_mb"] == 768


def test_delete_template_endpoint(client, tracker):
    template_id = f"{tracker['prefix']}-delete-template"
    create = client.post(
        "/api/v1/templates",
        json={
            "id": template_id,
            "name": "delete-template",
            "image": "alpine:3.19",
            "command": "sleep 3600",
            "cpu_millicores": 500,
            "memory_mb": 512,
        },
    )
    assert create.status_code == 201, create.text
    delete = client.delete(f"/api/v1/templates/{template_id}")
    assert delete.status_code == 200
    assert delete.json()["message"] == "Template deleted successfully"


def test_create_sandbox_endpoint(created_sandbox):
    assert created_sandbox


def test_get_sandbox_endpoint(client, created_sandbox):
    response = client.get(f"/api/v1/sandboxes/{created_sandbox}")
    assert response.status_code == 200
    assert response.json()["data"]["id"] == created_sandbox
    assert "workspace_path" not in response.json()["data"]


def test_list_sandboxes_endpoint(client, created_sandbox):
    response = client.get("/api/v1/sandboxes")
    assert response.status_code == 200
    ids = [item["id"] for item in response.json()["data"]["sandboxes"]]
    assert created_sandbox in ids


def test_query_sandboxes_endpoint(client, tracker, created_sandbox):
    response = client.post(
        "/api/v1/sandboxes/query",
        json={"metadata": {"tenant_id": tracker["tenant_id"]}, "page": 1, "page_size": 50},
    )
    assert response.status_code == 200
    ids = [item["id"] for item in response.json()["data"]["sandboxes"]]
    assert created_sandbox in ids


def test_update_sandbox_endpoint(client, created_sandbox):
    response = client.patch(
        f"/api/v1/sandboxes/{created_sandbox}",
        json={"name": "renamed-sandbox", "metadata": {"branch": "main"}},
    )
    assert response.status_code == 200
    assert response.json()["data"]["name"] == "renamed-sandbox"
    assert response.json()["data"]["metadata"]["branch"] == "main"


def test_sandbox_status_endpoint(client, created_sandbox):
    response = client.get(f"/api/v1/sandboxes/{created_sandbox}/status")
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "running"


def test_exec_endpoint(client, created_sandbox):
    response = client.post(f"/api/v1/sandboxes/{created_sandbox}/exec", json={"command": ["echo", "hello"]})
    assert response.status_code == 200
    assert response.json()["data"]["exit_code"] == 0
    assert response.json()["data"]["stdout"].strip() == "hello"


def test_files_endpoints(client, created_sandbox):
    create_dir = client.put(
        f"/api/v1/sandboxes/{created_sandbox}/files",
        params={"path": "/workspace/test-dir", "kind": "directory"},
    )
    assert create_dir.status_code == 200, create_dir.text

    write_file = client.put(
        f"/api/v1/sandboxes/{created_sandbox}/files",
        params={"path": "/workspace/test-dir/hello.txt", "kind": "file"},
        content=b"hello file\n",
        headers={"Content-Type": "text/plain; charset=utf-8"},
    )
    assert write_file.status_code == 200, write_file.text
    assert write_file.json()["data"]["size"] == len(b"hello file\n")

    read_file = client.get(
        f"/api/v1/sandboxes/{created_sandbox}/files",
        params={"path": "/workspace/test-dir/hello.txt", "view": "content"},
    )
    assert read_file.status_code == 200, read_file.text
    assert read_file.text == "hello file\n"

    tree = client.get(
        f"/api/v1/sandboxes/{created_sandbox}/files",
        params={"path": "/workspace", "view": "tree"},
    )
    assert tree.status_code == 200, tree.text
    root = tree.json()["data"]
    test_dir = next(item for item in root["children"] if item["path"] == "/workspace/test-dir")
    assert test_dir["is_dir"] is True
    assert any(child["path"] == "/workspace/test-dir/hello.txt" for child in test_dir["children"])

    delete_file = client.delete(
        f"/api/v1/sandboxes/{created_sandbox}/files",
        params={"path": "/workspace/test-dir/hello.txt", "recursive": "false"},
    )
    assert delete_file.status_code == 200, delete_file.text

    delete_dir = client.delete(
        f"/api/v1/sandboxes/{created_sandbox}/files",
        params={"path": "/workspace/test-dir", "recursive": "false"},
    )
    assert delete_dir.status_code == 200, delete_dir.text


def test_terminal_websocket_endpoint(client, created_sandbox):
    with client.websocket_connect(f"/api/v1/sandboxes/{created_sandbox}/terminal") as websocket:
        websocket.send_json({"type": "stdin", "data": "echo ws-ok\n"})
        data = wait_until(lambda: websocket.receive_json(), timeout=20, interval=0.1)
        assert data["type"] in {"stdout", "stderr"}
        while "ws-ok" not in data["data"]:
            data = websocket.receive_json()
        assert "ws-ok" in data["data"]


def test_stop_and_start_sandbox_endpoints(client, created_sandbox):
    stop = client.post(f"/api/v1/sandboxes/{created_sandbox}/stop", params={"timeout": "5s"})
    assert stop.status_code == 200
    wait_until(lambda: client.get(f"/api/v1/sandboxes/{created_sandbox}").json()["data"]["status"] == "stopped")
    start = client.post(f"/api/v1/sandboxes/{created_sandbox}/start")
    assert start.status_code == 200
    wait_until(lambda: client.get(f"/api/v1/sandboxes/{created_sandbox}").json()["data"]["status"] == "running")


def test_restart_sandbox_endpoint(client, created_sandbox):
    response = client.post(f"/api/v1/sandboxes/{created_sandbox}/restart", params={"timeout": "5s"})
    assert response.status_code == 200
    wait_until(lambda: client.get(f"/api/v1/sandboxes/{created_sandbox}").json()["data"]["status"] == "running")


def test_ttl_endpoints(client, created_sandbox):
    update = client.put(f"/api/v1/sandboxes/{created_sandbox}/ttl", json={"ttl_seconds": 300})
    assert update.status_code == 200
    get_ttl = client.get(f"/api/v1/sandboxes/{created_sandbox}/ttl")
    assert get_ttl.status_code == 200
    assert get_ttl.json()["data"]["ttl_seconds"] == 300
    renew = client.post(f"/api/v1/sandboxes/{created_sandbox}/renew", json={"ttl": 600})
    assert renew.status_code == 200
    assert renew.json()["data"]["ttl_seconds"] == 300


def test_ttl_renew_prevents_old_expiry(client, tracker, created_template):
    create = client.post(
        "/api/v1/sandboxes",
        json={
            "name": f"{tracker['prefix']}-ttl-renew",
            "template_id": created_template,
            "metadata": {"user_id": tracker["user_id"], "tenant_id": tracker["tenant_id"]},
        },
    )
    assert create.status_code == 201, create.text
    sandbox_id = create.json()["data"]["id"]
    tracker["sandboxes"].append(sandbox_id)
    wait_until(lambda: client.get(f"/api/v1/sandboxes/{sandbox_id}").json()["data"]["status"] == "running")

    update = client.put(f"/api/v1/sandboxes/{sandbox_id}/ttl", json={"ttl_seconds": 3})
    assert update.status_code == 200
    time.sleep(1.5)

    renew = client.post(f"/api/v1/sandboxes/{sandbox_id}/renew", json={"ttl": 4})
    assert renew.status_code == 200

    time.sleep(2.5)
    still_exists = client.get(f"/api/v1/sandboxes/{sandbox_id}")
    assert still_exists.status_code == 200, still_exists.text

    wait_until(lambda: client.get(f"/api/v1/sandboxes/{sandbox_id}").status_code == 404, timeout=15, interval=1)


def test_create_pool_endpoint(created_pool):
    assert created_pool


def test_get_pool_endpoint(client, created_pool):
    response = client.get(f"/api/v1/pools/{created_pool}")
    assert response.status_code == 200
    assert response.json()["data"]["template_id"] == created_pool


def test_list_pools_endpoint(client, created_pool):
    response = client.get("/api/v1/pools")
    assert response.status_code == 200
    ids = [item["template_id"] for item in response.json()["data"]["pools"]]
    assert created_pool in ids


def test_update_pool_endpoint(client, created_pool):
    response = client.put(f"/api/v1/pools/{created_pool}", json={"min_ready": 2})
    assert response.status_code == 200
    assert response.json()["data"]["min_ready"] == 2
    wait_until(lambda: client.get(f"/api/v1/pools/{created_pool}").json()["data"]["ready"] >= 2, timeout=180)


def test_delete_pool_endpoint(client, tracker):
    template_id = f"{tracker['prefix']}-delete-pool"
    create_template = client.post(
        "/api/v1/templates",
        json={
            "id": template_id,
            "name": "delete-pool-template",
            "image": "alpine:3.19",
            "command": "sleep 3600",
            "cpu_millicores": 500,
            "memory_mb": 512,
        },
    )
    assert create_template.status_code == 201, create_template.text
    create_pool = client.post(f"/api/v1/pools/{template_id}", json={"min_ready": 1})
    assert create_pool.status_code == 201, create_pool.text
    delete_pool = client.delete(f"/api/v1/pools/{template_id}")
    assert delete_pool.status_code == 200
    client.delete(f"/api/v1/templates/{template_id}")


def test_allocate_from_pool_via_create_sandbox(client, tracker, created_pool):
    response = client.post(
        "/api/v1/sandboxes",
        json={
            "name": f"{tracker['prefix']}-pool-sandbox",
            "template_id": created_pool,
            "metadata": {"tenant_id": tracker["tenant_id"], "user_id": tracker["user_id"]},
        },
    )
    assert response.status_code == 201, response.text
    sandbox_id = response.json()["data"]["id"]
    tracker["sandboxes"].append(sandbox_id)
    assert response.json()["data"]["pool_state"] == "allocated"


def test_webhook_delivery_for_pool_allocation(client, tracker, created_pool, created_webhook, webhook_receiver):
    _, received = webhook_receiver
    received.clear()

    response = client.post(
        "/api/v1/sandboxes",
        json={
            "name": f"{tracker['prefix']}-pool-webhook-sandbox",
            "template_id": created_pool,
            "metadata": {"tenant_id": tracker["tenant_id"], "user_id": tracker["user_id"]},
        },
    )
    assert response.status_code == 201, response.text
    sandbox_id = response.json()["data"]["id"]
    tracker["sandboxes"].append(sandbox_id)
    assert response.json()["data"]["pool_state"] == "allocated"

    wait_until(
        lambda: {"sandbox_started", "sandbox_ready"}.issubset({item["event_type"] for item in received}),
        timeout=60,
    )


def test_create_get_list_delete_expose_endpoints(client, tracker, created_sandbox):
    create = client.post(
        f"/api/v1/sandboxes/{created_sandbox}/exposes",
        json={"protocol": "http", "internal_port": 8000, "path": "/"},
    )
    assert create.status_code == 201, create.text
    expose_id = create.json()["data"]["id"]
    tracker["exposes"].append(expose_id)

    get_expose = client.get(f"/api/v1/exposes/{expose_id}")
    assert get_expose.status_code == 200
    assert get_expose.json()["data"]["id"] == expose_id

    list_exposes = client.get(f"/api/v1/sandboxes/{created_sandbox}/exposes")
    assert list_exposes.status_code == 200
    ids = [item["id"] for item in list_exposes.json()["data"]["exposes"]]
    assert expose_id in ids

    delete_expose = client.delete(f"/api/v1/exposes/{expose_id}")
    assert delete_expose.status_code == 200
    tracker["exposes"].remove(expose_id)


def test_webhook_crud_and_delivery_endpoints(client, tracker, created_template, created_webhook, webhook_receiver):
    server, received = webhook_receiver
    received.clear()
    get_webhook = client.get(f"/api/v1/webhooks/{created_webhook}")
    assert get_webhook.status_code == 200
    assert get_webhook.json()["data"]["id"] == created_webhook

    list_webhooks = client.get("/api/v1/webhooks", params={"user_id": tracker["user_id"]})
    assert list_webhooks.status_code == 200
    ids = [item["id"] for item in list_webhooks.json()["data"]]
    assert created_webhook in ids

    update_webhook = client.patch(
        f"/api/v1/webhooks/{created_webhook}",
        json={"name": "updated-webhook"},
    )
    assert update_webhook.status_code == 200
    assert update_webhook.json()["data"]["name"] == "updated-webhook"

    create_sandbox = client.post(
        "/api/v1/sandboxes",
        json={
            "name": f"{tracker['prefix']}-webhook-sandbox",
            "template_id": created_template,
            "metadata": {"user_id": tracker["user_id"], "tenant_id": tracker["tenant_id"]},
        },
    )
    assert create_sandbox.status_code == 201, create_sandbox.text
    sandbox_id = create_sandbox.json()["data"]["id"]
    tracker["sandboxes"].append(sandbox_id)
    client.delete(f"/api/v1/sandboxes/{sandbox_id}")
    wait_until(lambda: len(received) >= 3, timeout=60)
    event_types = {item["event_type"] for item in received}
    assert {"sandbox_started", "sandbox_ready", "sandbox_deleted"}.issubset(event_types)


def test_delete_webhook_endpoint(client, tracker):
    webhook_id = f"{tracker['prefix']}-delete-webhook"
    create = client.post(
        "/api/v1/webhooks",
        json={
            "id": webhook_id,
            "name": "delete-webhook",
            "user_id": tracker["user_id"],
            "url": "http://127.0.0.1:9/hook",
        },
    )
    assert create.status_code == 201, create.text
    delete = client.delete(f"/api/v1/webhooks/{webhook_id}")
    assert delete.status_code == 200


def test_metrics_snapshot_endpoint(client, tracker):
    snapshot = client.get("/api/v1/metrics/snapshot")
    assert snapshot.status_code == 200
    data = snapshot.json()["data"]
    assert "live" in data
    assert data["live"]["total"] >= 1


def test_delete_sandbox_endpoint(client, tracker, created_template):
    create = client.post(
        "/api/v1/sandboxes",
        json={
            "name": f"{tracker['prefix']}-delete-sandbox",
            "template_id": created_template,
            "metadata": {"user_id": tracker["user_id"], "tenant_id": tracker["tenant_id"]},
        },
    )
    assert create.status_code == 201, create.text
    sandbox_id = create.json()["data"]["id"]
    delete = client.delete(f"/api/v1/sandboxes/{sandbox_id}")
    assert delete.status_code == 200
