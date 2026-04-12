# API Reference

Base URL: `http://your-host:8080`

All request and response bodies use `application/json`. Timestamps are ISO 8601 UTC strings.

---

## Table of Contents

- [Health](#health)
- [Templates](#templates)
- [Sandboxes](#sandboxes)
  - [Lifecycle](#lifecycle)
  - [Files & Exec](#files--exec)
  - [TTL](#ttl)
  - [Service Exposes](#service-exposes)
- [Pools](#pools)
- [Webhooks](#webhooks)
- [Metrics](#metrics)

---

## Health

### `GET /health`

Returns service health status.

```bash
curl http://localhost:8080/health
```

**Response `200`**
```json
{ "status": "ok" }
```

---

## Templates

Templates define the resource blueprint for sandboxes (image, CPU, memory, env vars, TTL, etc.).

### Template Object

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique template ID (auto-generated) |
| `name` | string | Human-readable name |
| `description` | string? | Optional description |
| `image` | string | Container image (e.g. `ubuntu:22.04`) |
| `command` | string? | Override entrypoint (e.g. `/bin/bash`) |
| `env` | string[] | Environment variables as `KEY=VALUE` strings |
| `host_path_mounts` | HostPathMount[] | Host directory mounts |
| `cpu_millicores` | integer | CPU limit in millicores (100–128000) |
| `cpu_request` | integer? | CPU request in millicores (default: same as limit) |
| `memory_mb` | integer | Memory limit in MB (128–131072) |
| `memory_request` | integer? | Memory request in MB (default: same as limit) |
| `ttl_seconds` | integer? | Default sandbox lifetime in seconds (60–86400) |
| `metadata` | object? | Arbitrary key-value metadata |
| `created_at` | string | ISO 8601 creation timestamp |
| `updated_at` | string | ISO 8601 last-updated timestamp |

**HostPathMount object:**

| Field | Type | Description |
|-------|------|-------------|
| `host_path` | string | Absolute path on the host node |
| `container_path` | string | Mount path inside the container |
| `read_only` | boolean | Whether the mount is read-only |

---

### `POST /api/v1/templates`

Create a new template.

```bash
curl -X POST http://localhost:8080/api/v1/templates \
  -H "Content-Type: application/json" \
  -d '{
    "name": "ubuntu-dev",
    "image": "ubuntu:22.04",
    "cpu_millicores": 1000,
    "memory_mb": 512,
    "env": ["TERM=xterm-256color", "LANG=en_US.UTF-8"],
    "ttl_seconds": 3600
  }'
```

**Response `200`** — the created Template object.

---

### `GET /api/v1/templates`

List all templates.

**Query parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `name` | string? | Filter by name (substring match) |
| `user_id` | string? | Filter by `metadata.user_id` |

```bash
curl "http://localhost:8080/api/v1/templates?name=ubuntu"
```

**Response `200`**
```json
{
  "templates": [ /* Template[] */ ],
  "total": 3
}
```

---

### `GET /api/v1/templates/{template_id}`

Get a single template by ID.

**Response `200`** — Template object.  
**Response `404`** — Template not found.

---

### `PATCH /api/v1/templates/{template_id}`

Update a template. All fields are optional — only provided fields are updated.

```bash
curl -X PATCH http://localhost:8080/api/v1/templates/tpl-abc123 \
  -H "Content-Type: application/json" \
  -d '{"memory_mb": 1024, "ttl_seconds": 7200}'
```

**Response `200`** — Updated Template object.

---

### `DELETE /api/v1/templates/{template_id}`

Delete a template. Also deletes any associated Pool configuration.

**Response `200`**
```json
{ "status": "deleted", "id": "tpl-abc123" }
```

---

## Sandboxes

### Sandbox Object

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique sandbox ID |
| `name` | string | Display name (set at allocation time) |
| `template_id` | string | ID of the template used |
| `image` | string | Container image |
| `cpu_millicores` | integer | CPU limit from template |
| `memory_mb` | integer | Memory limit from template |
| `status` | SandboxStatus | Current status |
| `terminating` | boolean | Whether the pod is being deleted |
| `pool_state` | PoolState | Pool membership state |
| `workspace_path` | string | Working directory inside the container |
| `metadata` | object | Key-value metadata set at creation |
| `allocated_at` | string? | When the sandbox was allocated from a pool |
| `created_at` | string | ISO 8601 creation timestamp |
| `updated_at` | string | ISO 8601 last-updated timestamp |
| `ttl_seconds` | integer | Configured TTL |
| `expires_at` | string? | ISO 8601 expiry timestamp |
| `time_remaining_seconds` | integer | Seconds until expiry (0 if no TTL) |

**SandboxStatus values:** `created` · `running` · `stopped` · `exited` · `unknown` · `pooled` · `creating`

**PoolState values:** `none` · `creating` · `available` · `allocated` · `failed`

---

### Lifecycle

#### `POST /api/v1/sandboxes/allocate`

Create or allocate a sandbox. If a warm pool exists for the template, an available sandbox is claimed immediately (zero wait). Otherwise a new sandbox is created and waits until the pod is ready.

```bash
curl -X POST http://localhost:8080/api/v1/sandboxes/allocate \
  -H "Content-Type: application/json" \
  -d '{
    "template_id": "tpl-abc123",
    "name": "my-sandbox",
    "metadata": { "user_id": "user-xyz", "project": "demo" },
    "ttl_seconds": 3600
  }'
```

**Request body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `template_id` | string | ✅ | Template to use |
| `name` | string? | | Human-readable name |
| `metadata` | object? | | Arbitrary key-value pairs (e.g. `user_id`) |
| `ttl_seconds` | integer? | | Override template TTL |

**Response `200`** — Sandbox object (status `running` when returned).

---

#### `POST /api/v1/sandboxes`

Low-level sandbox creation (does not use pools). Prefer `/allocate` for application use.

Same request body as `/allocate` plus:

| Field | Type | Description |
|-------|------|-------------|
| `pool_state` | string? | Internal pool state (default: `none`) |
| `wait_ready` | boolean? | Wait for pod ready before returning (default: `true`) |

---

#### `GET /api/v1/sandboxes`

List sandboxes.

**Query parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `template_id` | string? | Filter by template |
| `status` | string? | Filter by status |
| `pool_state` | string? | Filter by pool state |
| `name` | string? | Filter by name (substring) |
| `page` | integer? | Page number (default: 1) |
| `page_size` | integer? | Page size (default: 50) |

**Response `200`**
```json
{
  "sandboxes": [ /* Sandbox[] */ ],
  "total": 12,
  "page": 1,
  "page_size": 50
}
```

---

#### `POST /api/v1/sandboxes/query`

Query sandboxes with metadata filters.

```bash
curl -X POST http://localhost:8080/api/v1/sandboxes/query \
  -H "Content-Type: application/json" \
  -d '{
    "metadata": { "user_id": "user-xyz" },
    "status": "running"
  }'
```

---

#### `GET /api/v1/sandboxes/{sandbox_id}`

Get a single sandbox by ID.

---

#### `PATCH /api/v1/sandboxes/{sandbox_id}`

Update sandbox metadata or name.

---

#### `DELETE /api/v1/sandboxes/{sandbox_id}`

Delete a sandbox (stops and removes the pod).

**Query parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `timeout` | string? | Grace period before force-kill (e.g. `30s`, `5m`). Default: `10s` |

---

#### `POST /api/v1/sandboxes/{sandbox_id}/start`

Start a stopped sandbox (scales pod replicas to 1).

---

#### `POST /api/v1/sandboxes/{sandbox_id}/stop`

Stop a running sandbox (scales pod replicas to 0).

**Query parameters:** `timeout` — pod termination grace period.

---

#### `POST /api/v1/sandboxes/{sandbox_id}/restart`

Restart a sandbox pod (deletes current pod, Deployment creates a new one).

**Query parameters:** `timeout` — pod termination grace period.

---

### Files & Exec

#### `POST /api/v1/sandboxes/{sandbox_id}/exec`

Execute a command inside a running sandbox.

```bash
curl -X POST http://localhost:8080/api/v1/sandboxes/sbx-abc/exec \
  -H "Content-Type: application/json" \
  -d '{"command": ["ls", "-la", "/workspace"], "timeout": 10}'
```

**Request body:**

| Field | Type | Description |
|-------|------|-------------|
| `command` | string[] | Command and arguments |
| `timeout` | integer | Seconds to wait (default: 30) |

**Response `200`**
```json
{
  "stdout": "total 4\ndrwxr-xr-x ...",
  "stderr": "",
  "exit_code": 0
}
```

---

#### `GET /api/v1/sandboxes/{sandbox_id}/files`

List files in a directory inside the sandbox.

**Query parameters:** `path` — directory path (default: `/workspace`).

**Response `200`**
```json
{
  "entries": [
    { "name": "main.py", "type": "file", "size": 1024 },
    { "name": "src", "type": "directory", "size": 0 }
  ],
  "path": "/workspace"
}
```

---

#### `PUT /api/v1/sandboxes/{sandbox_id}/files`

Write a file inside the sandbox.

**Request body:**

| Field | Type | Description |
|-------|------|-------------|
| `path` | string | Absolute path inside the container |
| `content` | string | File content (UTF-8) |

---

#### `DELETE /api/v1/sandboxes/{sandbox_id}/files`

Delete a file inside the sandbox.

**Query parameters:** `path` — file path to delete.

---

#### WebSocket: `ws://{host}/api/v1/sandboxes/{sandbox_id}/terminal`

Open a WebSocket PTY terminal session. Send/receive raw terminal data. The connection is proxied to a `kubectl exec` session inside the sandbox pod.

---

### TTL

#### `POST /api/v1/sandboxes/{sandbox_id}/renew`

Renew the sandbox TTL (extend its lifetime).

```bash
curl -X POST http://localhost:8080/api/v1/sandboxes/sbx-abc/renew \
  -H "Content-Type: application/json" \
  -d '{"ttl": 3600}'
```

**Request body:** `ttl` (integer) — new TTL in seconds from now.

---

#### `PUT /api/v1/sandboxes/{sandbox_id}/ttl`

Set an absolute TTL (seconds from now).

---

#### `GET /api/v1/sandboxes/{sandbox_id}/ttl`

Get current TTL info.

---

### Service Exposes

Expose a sandbox's internal port via a Kubernetes Service + Ingress.

#### `POST /api/v1/sandboxes/{sandbox_id}/exposes`

Create an expose.

```bash
curl -X POST http://localhost:8080/api/v1/sandboxes/sbx-abc/exposes \
  -H "Content-Type: application/json" \
  -d '{"port": 8888, "protocol": "http"}'
```

**Request body:**

| Field | Type | Description |
|-------|------|-------------|
| `port` | integer | Container port to expose |
| `protocol` | string | `http` or `tcp` |
| `subdomain` | string? | Custom subdomain prefix |

**Response `200`** — ServiceExpose object with `url` field.

---

#### `GET /api/v1/sandboxes/{sandbox_id}/exposes`

List all exposes for a sandbox.

---

#### `GET /api/v1/exposes/{expose_id}`

Get a single expose.

---

#### `DELETE /api/v1/exposes/{expose_id}`

Delete an expose (removes Service and Ingress).

---

## Pools

Pools maintain a warm inventory of pre-created sandboxes for zero-latency allocation.

### Pool Status Object

| Field | Type | Description |
|-------|------|-------------|
| `template_id` | string | Associated template |
| `enabled` | boolean | Whether the pool is active |
| `min_ready` | integer | Minimum warm sandbox count |
| `target_ready` | integer | Target warm sandbox count |
| `max_creating` | integer | Max concurrent creations |
| `ready` | integer | Current ready count |
| `creating` | integer | Currently creating |
| `allocated` | integer | Allocated (in use) |
| `failed` | integer | Failed creations |
| `created_at` | string | Pool creation timestamp |
| `updated_at` | string | Last updated timestamp |

---

### `POST /api/v1/pools/{template_id}`

Create a pool for a template.

```bash
curl -X POST http://localhost:8080/api/v1/pools/tpl-abc123 \
  -H "Content-Type: application/json" \
  -d '{"min_ready": 2, "target_ready": 5, "max_creating": 3}'
```

**Request body:**

| Field | Type | Description |
|-------|------|-------------|
| `min_ready` | integer | Minimum warm sandboxes to maintain |
| `target_ready` | integer? | Target warm count (defaults to `min_ready`) |
| `max_creating` | integer | Max concurrent sandbox creations |

---

### `GET /api/v1/pools`

List all pool statuses.

---

### `GET /api/v1/pools/{template_id}`

Get pool status for a specific template.

---

### `PUT /api/v1/pools/{template_id}`

Update pool configuration (triggers immediate reconcile).

---

### `DELETE /api/v1/pools/{template_id}`

Delete the pool. Non-allocated sandboxes are cleaned up; sandboxes currently in use (`ALLOCATED` state) are left running until they are deleted normally.

---

## Webhooks

Register HTTP endpoints to receive sandbox lifecycle event notifications.

### Webhook Object

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique webhook ID |
| `url` | string | Target URL for event delivery |
| `events` | string[] | Events to subscribe to |
| `secret` | string? | HMAC signing secret |
| `user_id` | string | Owner identifier |
| `created_at` | string | Creation timestamp |

**Event types:** `sandbox_started` · `sandbox_ready` · `sandbox_deleted`

### Webhook Payload

```json
{
  "event": "sandbox_ready",
  "sandbox": {
    "id": "sbx-abc123",
    "name": "my-sandbox",
    "template_id": "tpl-ubuntu",
    "image": "ubuntu:22.04",
    "cpu_millicores": 1000,
    "memory_mb": 512,
    "status": "running",
    "pool_state": "allocated",
    "workspace_path": "/workspace",
    "metadata": { "user_id": "user-xyz" },
    "created_at": "2025-01-01T00:00:00Z",
    "updated_at": "2025-01-01T00:00:05Z",
    "ttl_seconds": 3600,
    "expires_at": "2025-01-01T01:00:05Z",
    "time_remaining_seconds": 3598
  },
  "template": { /* Template object */ },
  "namespace": "default",
  "pod_name": "sbx-abc123-xxxx",
  "pod_ip": "10.244.0.5",
  "node_name": "k3s-node-1"
}
```

For `sandbox_deleted`, the payload also includes `"deletion_reason": "ttl_expired" | "manual"`.

---

### `POST /api/v1/webhooks`

Create a webhook.

```bash
curl -X POST http://localhost:8080/api/v1/webhooks \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://your-server.com/hooks/litterbox",
    "events": ["sandbox_ready", "sandbox_deleted"],
    "user_id": "user-xyz",
    "secret": "your-signing-secret"
  }'
```

---

### `GET /api/v1/webhooks`

List webhooks.

**Query parameters:** `user_id` — filter by owner.

---

### `GET /api/v1/webhooks/{webhook_id}`

Get a single webhook.

---

### `PATCH /api/v1/webhooks/{webhook_id}`

Update a webhook (URL, events, secret).

---

### `DELETE /api/v1/webhooks/{webhook_id}`

Delete a webhook.

---

## Metrics

### `GET /metrics`

Prometheus scrape endpoint. Returns metrics in the Prometheus text exposition format.

Key metrics exposed:

| Metric | Type | Description |
|--------|------|-------------|
| `sandbox_create_duration_seconds` | Histogram | End-to-end sandbox creation latency |
| `sandbox_creates_total` | Counter | Total sandbox creation attempts |
| `sandbox_create_errors_total` | Counter | Total failed creations |
| `sandbox_pool_hits_total` | Counter | Pool allocation hits |

---

### `GET /api/v1/metrics/snapshot`

Returns an in-memory 1-hour sliding window metrics snapshot as JSON.

```bash
curl http://localhost:8080/api/v1/metrics/snapshot | jq .
```

**Response `200`**
```json
{
  "window_hours": 1,
  "total_creates": 42,
  "success_rate": 0.976,
  "latency_p50_ms": 380,
  "latency_p95_ms": 12400,
  "latency_p99_ms": 45000,
  "pool_hit_rate": 0.714,
  "by_template": {
    "tpl-ubuntu": {
      "total": 30,
      "success": 29,
      "p50_ms": 320,
      "pool_hits": 22
    }
  }
}
```
