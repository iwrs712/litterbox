<div align="center">

# 🐱 Litterbox

**Secure sandbox orchestration for AI agents.**

Kubernetes-native. REST API and an E2B-compatible control plane. VM-level isolation with Kata Containers.
<br>

[简体中文](README.zh.md) · [API Reference](docs/api-reference.md) · [E2B Guide](orchestrator/docs/API.md) · [Configuration](docs/configuration.md) · [Sandbox Controller](controller/README.md)

</div>

<br>

## What is Litterbox?

Define a template, and Litterbox provisions an isolated sandbox on Kubernetes, manages its lifecycle, and exposes services on demand. Each sandbox runs in its own VM with a separate guest kernel, so untrusted code cannot reach the host or other workloads.

```text
POST /e2b/sandboxes       create a sandbox with the E2B SDK
POST /api/v1/sandboxes    native REST control plane
                          exec, files and PTY through envd
                          suspend on TTL, delete on demand
```

<br>

## Features

| Feature | Description |
|---|---|
| **VM isolation** | Sandboxes run under a Kata Containers RuntimeClass with their own guest kernel. |
| **Warm pool** | Pre-boots sandboxes per template for low-latency allocation. |
| **Workspace** | One persistent `/workspace` PVC per sandbox, retained across suspend and resume. |
| **E2B compatible** | Official E2B SDKs can create, connect, pause, resume and kill sandboxes. |
| **CRD lifecycle** | A `Sandbox` custom resource and controller: level-triggered reconciliation, informer-cached reads, self-healing Pods, controller-driven TTL. |
| **Lifecycle** | TTL auto-suspension, warm-pool reconciliation, sandbox lock, permanent delete. |
| **Terminal & files** | Command execution, file I/O and PTY sessions through the envd data plane. |
| **Expose** | Publish any sandbox port through a Service and Ingress. |
| **Webhooks** | Async `sandbox_started`, `sandbox_ready` and `sandbox_deleted` events. |

<br>

## Screenshots

<table>
<tr>
<td><img src="docs/imgs/dashboard.png" alt="Dashboard" width="100%"></td>
<td><img src="docs/imgs/sandboxes.png" alt="Sandboxes" width="100%"></td>
</tr>
<tr>
<td><img src="docs/imgs/pool.png" alt="Warm Pools" width="100%"></td>
<td><img src="docs/imgs/terminal.png" alt="Terminal" width="100%"></td>
</tr>
</table>

<br>

## Architecture

```mermaid
flowchart LR
    subgraph Clients["Clients"]
        Dashboard["Dashboard"]
        RestClient["REST clients"]
        Sdk["E2B SDK"]
    end

    subgraph Orchestrator["Orchestrator  (FastAPI + Celery)"]
        Rest["REST API\n/api/v1"]
        E2B["E2B API\n/e2b"]
        Proxy["envd proxy"]
    end

    Controller["sandbox-controller"]
    Redis[("Redis\nCelery · pool locks")]

    subgraph Cluster["Kubernetes"]
        Sandbox["Sandbox Pod\nmain + envd + /workspace PVC"]
        Runtime["RuntimeClass"]
        NetPol["NetworkPolicy"]
    end

    Dashboard --> Rest
    RestClient --> Rest
    Sdk --> E2B
    Sdk -->|"envd"| Proxy
    Dashboard -->|"envd"| Proxy
    Rest -->|"Sandbox CRs"| Controller
    Controller -->|"Pod + PVC"| Sandbox
    E2B --> Rest
    Orchestrator <--> Redis
    Proxy -->|"Pod IP :49983"| Sandbox
    Runtime -.-> Sandbox
    NetPol -.-> Sandbox
```

- **Control plane.** `/api/v1` manages templates, pools, webhooks, exposes and sandbox lifecycle. `/e2b` adapts the same services to the E2B SDK. Template, pool and webhook metadata live in ConfigMaps.
- **Sandbox lifecycle.** The API writes `Sandbox` custom resources; the controller owns Pods and PVCs, publishes `status.phase`, handles TTL expiry, and repairs deleted Pods. REST and E2B clients never talk to Kubernetes workloads directly.
- **Data plane.** When enabled, each sandbox runs an envd process on port `49983`. The orchestrator proxies authenticated traffic to the Pod, either at `/api/v1/sandboxes/{id}/envd/*` or through E2B host routing.
- **Isolation.** Sandboxes use a Kata RuntimeClass, a per-sandbox `/workspace` PVC, and optionally a NetworkPolicy allowlist for ingress and egress.

<br>

## Quick Start

| | Version |
|---|---|
| Kubernetes | k3s recommended |
| Docker Compose | v2+ |
| Python | 3.12+ |
| Node.js | 18+ |

### 1. Start the backend

```bash
cd orchestrator
cp .env.example .env      # set KUBECONFIG, K8S_NAMESPACE, BASE_DOMAIN
docker compose up --build
```

```bash
curl http://localhost:8080/health
# {"success": true, "message": "Litterbox API is running"}
```

> If `ORCHESTRATOR__AUTH__BEARER_TOKEN` is set, add `Authorization: Bearer <token>` to REST calls.

### 2. Create a template

```bash
curl -s -X POST http://localhost:8080/api/v1/templates \
  -H "Content-Type: application/json" \
  -d '{
    "id": "ubuntu",
    "name": "ubuntu",
    "image": "ubuntu:22.04",
    "command": "sleep infinity",
    "cpu_millicores": 500,
    "memory_mb": 512,
    "ttl_seconds": 3600
  }'
```

### 3. Create a sandbox

```bash
pip install e2b
```

```python
from e2b import Sandbox

sandbox = Sandbox.create(
    template="ubuntu",
    api_url="http://localhost:8080/e2b",
    domain="localhost",
)
print(sandbox.sandbox_id)
```

Command execution and file access require envd; see [E2B Compatibility](#e2b-compatibility).

### 4. Start the dashboard

```bash
cd dashboard
cp .env.example .env      # set VITE_API_BASE_URL and VITE_API_BEARER_TOKEN
npm install && npm run dev
```

Open **http://localhost:5173**.

<br>

## E2B Compatibility

Litterbox implements a compatible subset of the E2B control plane and envd data plane, and can run the official E2B SDKs directly.

To use it:

- Set `ORCHESTRATOR__E2B__ENABLED=true` and an `ORCHESTRATOR__E2B__API_KEY` (empty falls back to the orchestrator bearer token).
- Point `ORCHESTRATOR__E2B__DOMAIN` at a wildcard domain whose DNS and TLS certificate route to the orchestrator.
- Install envd on the Kubernetes nodes and enable it with `ORCHESTRATOR__ENVD__ENABLED=true`.
- Create the template first; `Sandbox.create` selects an existing template and does not build images.

```python
from e2b import Sandbox

config = {
    "api_url": "https://orchestrator.example.com/e2b",
    "domain": "sandbox.example.com",
    "api_key": "<E2B_API_KEY>",
}

sandbox = Sandbox.create(template="ubuntu", timeout=300, **config)

print(sandbox.commands.run("uname -a").stdout)
sandbox.files.write("/workspace/notes.txt", "hello")
print(sandbox.files.read("/workspace/notes.txt"))

sandbox.pause(keep_memory=False)      # keep the workspace PVC
sandbox = Sandbox.connect(sandbox.sandbox_id, **config)
sandbox.set_timeout(600)
sandbox.kill()                        # permanent; deletes the workspace PVC
```

| Capability | Status |
|---|---|
| `Sandbox.create` / `connect` / `kill` | Supported |
| `pause(keep_memory=False)` | Supported; keeps `/workspace` |
| `pause(keep_memory=True)` | Not supported (`409`) |
| `set_timeout` | Supported; `0` disables expiry |
| Commands, files, PTY | Supported through envd |

Not supported: memory snapshots (`pause(keep_memory=True)`), fork, template builds, E2B volumes, and network allow/deny policies.

> The SDK context manager calls `kill()` on exit. Use `pause(keep_memory=False)` to keep the workspace.
>
> 📖 **Full E2B guide** → [orchestrator/docs/API.md](orchestrator/docs/API.md)

<br>

## API

| Group | Method | Path |
|---|---|---|
| Templates | `POST` / `GET` / `PATCH` / `DELETE` | `/api/v1/templates` |
| Sandboxes | `POST` / `GET` / `PATCH` / `DELETE` | `/api/v1/sandboxes` |
| Lifecycle | `POST` | `/api/v1/sandboxes/:id/suspend` · `resume` · `lock` · `unlock` · `renew` |
| Exposes | `POST` / `GET` / `DELETE` | `/api/v1/sandboxes/:id/exposes` |
| Pools | `POST` / `GET` / `PUT` / `DELETE` | `/api/v1/pools/:template_id` |
| Webhooks | `POST` / `GET` / `PATCH` / `DELETE` | `/api/v1/webhooks` |
| E2B control plane | `POST` / `GET` / `DELETE` | `/e2b/sandboxes` · `/e2b/sandboxes/:id` |
| E2B lifecycle | `POST` | `/e2b/sandboxes/:id/connect` · `pause` · `timeout` |
| envd path proxy | HTTP / Connect RPC | `/api/v1/sandboxes/:id/envd/*` |

> 📖 **Full API reference** → [docs/api-reference.md](docs/api-reference.md)

<br>

## Configuration

Configuration comes from `config.toml`, overridden by `ORCHESTRATOR__<SECTION>__<KEY>` environment variables.

| Variable | Default | Description |
|---|---|---|
| `ORCHESTRATOR__KUBERNETES__KUBECONFIG` | *empty (in-cluster)* | Path to kubeconfig |
| `ORCHESTRATOR__KUBERNETES__NAMESPACE` | `default` | Namespace for sandbox resources |
| `ORCHESTRATOR__KUBERNETES__RUNTIME_CLASS` | `kata-clh` | RuntimeClass for VM isolation, applied if it exists |
| `ORCHESTRATOR__WORKSPACE__STORAGE_CLASS` | `litterbox-workspace-lvm` | StorageClass for `/workspace` PVCs |
| `ORCHESTRATOR__ENVD__ENABLED` | `false` | Inject and start envd in sandbox pods |
| `ORCHESTRATOR__ENVD__VERSION` | `0.1.0` | envd version and node selector label |
| `ORCHESTRATOR__E2B__ENABLED` | `true` | Expose the E2B control plane |
| `ORCHESTRATOR__E2B__API_KEY` | *empty* | E2B `X-API-Key`; falls back to the bearer token |
| `ORCHESTRATOR__E2B__DOMAIN` | `sandbox.example.com` | Wildcard data-plane domain |
| `ORCHESTRATOR__SANDBOX__BASE_DOMAIN` | `example.com` | Wildcard domain for HTTP exposes |
| `ORCHESTRATOR__TTL__DEFAULT_TTL_SECONDS` | `1800` | Default sandbox lifetime |
| `ORCHESTRATOR__CELERY__BROKER_URL` | `redis://127.0.0.1:6379/2` | Celery broker URL |
| `ORCHESTRATOR__AUTH__BEARER_TOKEN` | *empty* | Optional bearer token for `/api/v1` |

> 📖 **Full configuration reference** → [docs/configuration.md](docs/configuration.md)

<br>

## Documentation

| | |
|---|---|
| [**ARCHITECTURE.md**](orchestrator/ARCHITECTURE.md) | Internal design, data flow, component boundaries |
| [**E2B API Guide**](orchestrator/docs/API.md) | E2B compatibility, SDK examples, raw endpoints |
| [**docs/api-reference.md**](docs/api-reference.md) | Full API reference |
| [**docs/configuration.md**](docs/configuration.md) | All configuration options |
| [**docs/development.md**](docs/development.md) | Local development |

<br>

---

## Contributing

Issues and pull requests are welcome. Please read [docs/development.md](docs/development.md) first.
