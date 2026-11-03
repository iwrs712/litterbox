# API Reference

Base URL: `http://your-host:8080`

All request and response bodies use `application/json`. Timestamps are ISO 8601 UTC strings.

Litterbox exposes two API surfaces:

| Surface | Prefix | Auth |
|---|---|---|
| Private REST API | `/api/v1` | `Authorization: Bearer <ORCHESTRATOR__AUTH__BEARER_TOKEN>` when configured |
| E2B-compatible control plane | `/e2b` | `X-API-Key` (or `X-Access-Token` / Bearer) when configured |

When neither token is configured, both surfaces are open. The private API wraps every response in an [`ApiResponse`](#response-envelope); E2B routes return native E2B objects instead. See the [E2B API Guide](../orchestrator/docs/API.md) for SDK usage.

Command execution, file I/O and PTY sessions are **not** plain REST endpoints. They run through the envd data plane — see [Data Plane (envd)](#data-plane-envd).

---

## Table of Contents

- [Response Envelope](#response-envelope)
- [Health](#health)
- [Templates](#templates)
- [Sandboxes](#sandboxes)
  - [Lifecycle](#lifecycle)
  - [TTL](#ttl)
  - [Data Plane (envd)](#data-plane-envd)
  - [Service Exposes](#service-exposes)
- [Pools](#pools)
- [Webhooks](#webhooks)
- [E2B Control Plane](#e2b-control-plane)
- [Metrics](#metrics)

---

## Response Envelope

Private `/api/v1` endpoints return:

```json
{
  "success": true,
  "message": "optional message",
  "data": {}
}
```

Errors return:

```json
{
  "success": false,
  "error": "human-readable error"
}
```

E2B endpoints return native E2B objects and errors as `{"code": "...", "message": "..."}`.

---

## Health

### `GET /health`

```bash
curl http://localhost:8080/health
```

**Response `200`**

```json
{ "success": true, "message": "Litterbox API is running" }
```

### `GET /`

Returns the service name and version.

```json
{ "message": "Litterbox API is running", "version": "1.0.0" }
```

---

## Templates

Templates define the image, resources, environment and workspace policy for sandboxes.

### Template Object

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Template ID. Supplied on create or auto-generated |
| `name` | string | Human-readable name |
| `description` | string | Optional description |
| `image` | string | Container image (e.g. `ubuntu:22.04`) |
| `command` | string | Entrypoint command (a command list is joined with spaces) |
| `env` | string[] | Environment variables as `KEY=VALUE` strings |
| `host_path_mounts` | HostPathMount[] | Host directory mounts |
| `workspace` | WorkspaceConfigOverride? | Per-sandbox `/workspace` PVC policy; omitted fields inherit global defaults |
| `cpu_millicores` | integer | CPU limit in millicores (100–128000) |
| `cpu_request` | integer? | CPU request in millicores (default: limit) |
| `memory_mb` | integer | Memory limit in MB (128–131072) |
| `memory_request` | integer? | Memory request in MB (default: limit) |
| `ttl_seconds` | integer? | Default sandbox lifetime. `0` or omitted disables expiry; otherwise 60–86400 |
| `lifecycle` | SandboxLifecycle? | Kubernetes lifecycle hooks applied to every sandbox |
| `metadata` | object | Arbitrary string key-value metadata |
| `created_at` | string | ISO 8601 creation timestamp |
| `updated_at` | string | ISO 8601 last-updated timestamp |

**HostPathMount object**

| Field | Type | Description |
|-------|------|-------------|
| `host_path` | string | Absolute path on the host node |
| `container_path` | string | Mount path inside the container |
| `read_only` | boolean | Whether the mount is read-only |

**WorkspaceConfigOverride object**

| Field | Type | Description |
|-------|------|-------------|
| `enabled` | boolean? | Create and mount a workspace PVC |
| `mount_path` | string? | Absolute mount path (default `/workspace`) |
| `size` | string? | PVC size (default `1Gi`) |
| `storage_class` | string? | StorageClass (default from global workspace config) |

**SandboxLifecycle object**

| Field | Type | Description |
|-------|------|-------------|
| `postStart.exec.command` | string[] | Command run after container creation |
| `preStop.exec.command` | string[] | Command run before container termination |
| `preStop.terminationGracePeriodSeconds` | integer? | Termination grace period (1–300) |

> With `ORCHESTRATOR__ENVD__ENABLED=true`, envd owns `postStart`; templates that also define `postStart` are rejected at sandbox creation.

---

### `POST /api/v1/templates`

Create a template. Returns `201`.

```bash
curl -X POST http://localhost:8080/api/v1/templates \
  -H "Content-Type: application/json" \
  -d '{
    "id": "ubuntu",
    "name": "ubuntu-dev",
    "image": "ubuntu:22.04",
    "command": "sleep infinity",
    "cpu_millicores": 1000,
    "memory_mb": 512,
    "env": ["TERM=xterm-256color", "LANG=en_US.UTF-8"],
    "workspace": { "enabled": true, "size": "10Gi" },
    "ttl_seconds": 3600
  }'
```

**Response `201`** — the created Template object.

---

### `GET /api/v1/templates`

**Query parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `page` | integer? | Page number (default `1`) |
| `page_size` | integer? | Page size (default `10`, max `100`) |
| `name` | string? | Filter by name (substring match) |
| `user_id` | string? | Filter by `metadata.user_id` |

**Response `200`**

```json
{
  "success": true,
  "data": {
    "templates": [ /* Template[] */ ],
    "total": 3,
    "page": 1,
    "page_size": 10,
    "total_pages": 1
  }
}
```

---

### `GET /api/v1/templates/{template_id}`

Returns the Template object. `404` if missing.

---

### `PATCH /api/v1/templates/{template_id}`

Update any subset of template fields. Returns the updated Template object.

```bash
curl -X PATCH http://localhost:8080/api/v1/templates/ubuntu \
  -H "Content-Type: application/json" \
  -d '{"memory_mb": 1024, "ttl_seconds": 7200}'
```

---

### `DELETE /api/v1/templates/{template_id}`

Delete a template and its pool configuration. Existing sandboxes are not deleted.

```json
{ "success": true, "message": "Template deleted successfully" }
```

---

## Sandboxes

### Sandbox Object

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique sandbox ID (also the Sandbox CR and Pod name) |
| `name` | string | Display name set at allocation time |
| `template_id` | string | Template used |
| `image` | string | Container image from the template |
| `cpu_millicores` | integer | CPU limit from the template |
| `memory_mb` | integer | Memory limit from the template |
| `status` | SandboxStatus | Current status |
| `terminating` | boolean | Whether the Sandbox CR is being deleted |
| `pool_state` | string | Pool membership state |
| `metadata` | object | Key-value metadata set at creation |
| `allocated_at` | string? | When allocated from a pool |
| `created_at` | string | ISO 8601 creation timestamp |
| `updated_at` | string | ISO 8601 last-updated timestamp |
| `ttl_seconds` | integer | Configured TTL (`0` = no expiry) |
| `expires_at` | string? | ISO 8601 expiry timestamp |
| `time_remaining_seconds` | integer | Seconds until expiry |
| `locked` | boolean | Business lock; blocks resume |
| `workspace` | WorkspaceConfig? | Resolved workspace policy |

**SandboxStatus values:** `created` · `creating` · `running` · `stopped` · `exited` · `unknown` · `pooled`

`stopped` means the sandbox is suspended: the controller removed the Pod and the workspace PVC is retained.

**PoolState values:** `none` · `creating` · `available` · `allocated` · `failed`

---

### Lifecycle

#### `POST /api/v1/sandboxes`

Create or allocate a sandbox. If an enabled warm pool exists for the template, an available sandbox is claimed immediately; otherwise a new sandbox is created and the request waits for the Pod to become ready.

```bash
curl -X POST http://localhost:8080/api/v1/sandboxes \
  -H "Content-Type: application/json" \
  -d '{
    "template_id": "ubuntu",
    "name": "my-sandbox",
    "metadata": { "user_id": "user-xyz" },
    "env": ["JOB_ID=1001"]
  }'
```

**Request body**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `template_id` | string | ✅ | Template to use |
| `name` | string? | | Human-readable name |
| `metadata` | object? | | Arbitrary key-value pairs |
| `env` | string[]? | | Extra `KEY=VALUE` variables; rejected when a warm pool is enabled |
| `workspace` | WorkspaceConfigOverride? | | Workspace override; rejected when a warm pool is enabled |

**Response `201`** — Sandbox object.

---

#### `GET /api/v1/sandboxes`

**Query parameters:** `page` (default `1`), `page_size` (default `20`), `status`, `name`, `template_id`, `pool_state`.

**Response `200`**

```json
{
  "success": true,
  "data": {
    "sandboxes": [ /* Sandbox[] */ ],
    "total": 12,
    "page": 1,
    "page_size": 20
  }
}
```

---

#### `POST /api/v1/sandboxes/query`

Query with a JSON body:

```json
{
  "page": 1,
  "page_size": 20,
  "template_id": "ubuntu",
  "status": "running",
  "pool_state": "",
  "name": "",
  "metadata": { "user_id": "user-xyz" }
}
```

Returns the same shape as `GET /api/v1/sandboxes`.

---

#### `GET /api/v1/sandboxes/{sandbox_id}`

Returns a Sandbox object. `404` if missing.

#### `GET /api/v1/sandboxes/{sandbox_id}/status`

Returns the same Sandbox object.

---

#### `PATCH /api/v1/sandboxes/{sandbox_id}`

Update `name` or `metadata`.

```json
{ "name": "renamed", "metadata": { "user_id": "user-abc" } }
```

---

#### `DELETE /api/v1/sandboxes/{sandbox_id}`

Permanently delete the sandbox CR. Kubernetes garbage collection removes its Pod and workspace PVC through `ownerReference`. To stop compute while keeping the workspace, use `suspend`.

```json
{ "success": true, "message": "Sandbox deleted successfully" }
```

---

#### `POST /api/v1/sandboxes/{sandbox_id}/suspend`

Patch `spec.state` to `Paused`. The controller deletes the Pod and keeps the workspace PVC. The configured TTL is preserved; `resume` resets the TTL clock.

```json
{ "success": true, "data": { /* Sandbox */ }, "message": "Sandbox suspended successfully" }
```

---

#### `POST /api/v1/sandboxes/{sandbox_id}/resume`

Patch `spec.state` to `Running` and reset `spec.ttlAnchor`. The controller recreates the Pod. Returns `409` if the sandbox is locked.

---

#### `POST /api/v1/sandboxes/{sandbox_id}/lock`

Set the sandbox lock. A locked sandbox can still be queried, suspended and deleted, but `resume` is rejected.

#### `POST /api/v1/sandboxes/{sandbox_id}/unlock`

Clear the sandbox lock.

---

### TTL

#### `POST /api/v1/sandboxes/{sandbox_id}/renew`

Renew from now by `ttl` seconds.

```json
{ "ttl": 3600 }
```

#### `PUT /api/v1/sandboxes/{sandbox_id}/ttl`

Set the TTL explicitly.

```json
{ "ttl_seconds": 3600 }
```

#### `GET /api/v1/sandboxes/{sandbox_id}/ttl`

```json
{
  "success": true,
  "data": {
    "ttl_seconds": 3600,
    "expires_at": "2026-01-01T01:00:00Z",
    "time_remaining": 3598,
    "ttl_enabled": true
  }
}
```

When the TTL expires, the controller **pauses** the sandbox (removes the Pod, keeps the PVC) and sets `status.pausedReason=TTLExpired` rather than deleting it.

---

### Data Plane (envd)

Command execution, file operations and PTY streams use the E2B envd protocol (Connect RPC), not plain JSON REST. Every sandbox runs an envd process on port `49983` when `ORCHESTRATOR__ENVD__ENABLED=true`.

Two routes reach it:

| Route | Auth | Use |
|---|---|---|
| `49983-{sandbox_id}.{ORCHESTRATOR__E2B__DOMAIN}` (Host routing) | `X-API-Key` / `X-Access-Token` | Official E2B SDKs |
| `/api/v1/sandboxes/{sandbox_id}/envd/{envd_path}` | Bearer token | Dashboard and diagnostics |

The orchestrator proxies both to the sandbox Pod IP; neither exposes envd directly. Use an E2B SDK for anything beyond diagnostics. See [E2B Compatibility](../README.md#e2b-compatibility) and the [E2B API Guide](../orchestrator/docs/API.md).

Example health probe through the path proxy:

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8080/api/v1/sandboxes/sbx-abc/envd/health
```

---

### Service Exposes

Expose a sandbox port through a Kubernetes Service, plus an Ingress for HTTP.

#### `POST /api/v1/sandboxes/{sandbox_id}/exposes`

The sandbox must be `running`.

```bash
curl -X POST http://localhost:8080/api/v1/sandboxes/sbx-abc/exposes \
  -H "Content-Type: application/json" \
  -d '{"name": "web", "protocol": "http", "internal_port": 8080, "path": "/"}'
```

**Request body**

| Field | Type | Description |
|-------|------|-------------|
| `name` | string? | Display name |
| `protocol` | string | `http` or `tcp` |
| `internal_port` | integer | Container port (1–65535) |
| `domain` | string? | Custom HTTP host; defaults to `{port}-{sandbox_id}.{base_domain}` |
| `path` | string? | HTTP path prefix (default `/`) |

**Response `201`**

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Expose ID |
| `sandbox_id` | string | Owning sandbox |
| `name` | string | Display name |
| `protocol` | string | `http` or `tcp` |
| `internal_port` | integer | Container port |
| `external_url` | string | Public URL (HTTP) |
| `domain` | string | HTTP host |
| `path` | string | HTTP path |
| `external_ip` | string | Node IP (TCP) |
| `external_port` | integer | NodePort (TCP) |
| `service_name` | string | Kubernetes Service |
| `ingress_name` | string | Kubernetes Ingress (HTTP) |
| `status` | string | `pending` · `ready` · `failed` |
| `message` | string | Status detail |
| `created_at` / `updated_at` | string | Timestamps |

#### `GET /api/v1/sandboxes/{sandbox_id}/exposes`

Returns `{"success": true, "data": {"exposes": [...], "total": n}}`.

#### `GET /api/v1/exposes/{expose_id}`

Returns one expose.

#### `DELETE /api/v1/exposes/{expose_id}`

Removes the Service and Ingress.

---

## Pools

Pools maintain a warm inventory of pre-created sandboxes for low-latency allocation. A pool is a `SandboxPool` custom resource; the controller maintains its supply. Allocation claims an `available` sandbox with an optimistic `resourceVersion` JSON Patch, so there is no global lock.

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
| `terminating` | integer | Sandboxes being deleted |

---

### `POST /api/v1/pools/{template_id}`

Create a pool. Returns `201` with a Pool Status object.

```bash
curl -X POST http://localhost:8080/api/v1/pools/ubuntu \
  -H "Content-Type: application/json" \
  -d '{"min_ready": 2, "target_ready": 5, "max_creating": 3}'
```

| Field | Type | Description |
|-------|------|-------------|
| `min_ready` | integer | Minimum warm sandboxes (1–50) |
| `target_ready` | integer? | Target warm count (1–100, defaults to `min_ready`) |
| `max_creating` | integer? | Max concurrent creations (1–20, default `5`) |

### `GET /api/v1/pools`

Returns `{"success": true, "data": {"pools": [...], "total": n}}`.

### `GET /api/v1/pools/{template_id}`

Returns one Pool Status object.

### `PUT /api/v1/pools/{template_id}`

Update any of `min_ready`, `target_ready`, `max_creating`. The controller watches the `SandboxPool` CR and converges. Setting `min_ready` to `0` disables the pool and removes warm, non-allocated sandboxes.

### `DELETE /api/v1/pools/{template_id}`

Delete the pool. Warm, non-allocated sandboxes are cleaned up; allocated sandboxes keep running.

---

## Webhooks

Register HTTP endpoints to receive sandbox lifecycle events.

### Webhook Object

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique webhook ID |
| `name` | string | Display name |
| `user_id` | string | Owner identifier |
| `url` | string | Delivery URL |
| `token` | string | Optional bearer token sent to the receiver |
| `template_ids` | string[] | Restrict to these templates (empty = all) |
| `events` | string[] | Subscribed events |
| `retry` | object | `{max_attempts, interval_ms, timeout_ms}` |
| `enabled` | boolean | Whether delivery is active |
| `created_at` / `updated_at` | string | Timestamps |

**Event types:** `sandbox_started` · `sandbox_ready` · `sandbox_deleted`

### Webhook Payload

```json
{
  "event_id": "evt-abc123",
  "event_type": "sandbox_ready",
  "occurred_at": "2026-01-01T00:00:00Z",
  "deletion_reason": "",
  "sandbox": { /* Sandbox object */ },
  "template": { /* Template object */ },
  "kubernetes": {
    "namespace": "default",
    "pod_name": "sbx-abc123-xxxx",
    "pod_ip": "10.42.0.5",
    "node_name": "k3s-node-1",
    "container_name": "main"
  }
}
```

For `sandbox_deleted`, `deletion_reason` may be `ttl_expired` or `manual`.

---

### `POST /api/v1/webhooks`

Returns `201`.

```bash
curl -X POST http://localhost:8080/api/v1/webhooks \
  -H "Content-Type: application/json" \
  -d '{
    "name": "runner",
    "user_id": "user-xyz",
    "url": "https://your-server.com/hooks/litterbox",
    "events": ["sandbox_ready", "sandbox_deleted"],
    "template_ids": ["ubuntu"],
    "retry": { "max_attempts": 5, "interval_ms": 200, "timeout_ms": 1000 }
  }'
```

### `GET /api/v1/webhooks`

Optional `user_id` query parameter. Returns `data` as a Webhook array.

### `GET /api/v1/webhooks/{webhook_id}`

Returns one Webhook object.

### `PATCH /api/v1/webhooks/{webhook_id}`

Update `name`, `url`, `token`, `template_ids`, `events`, `retry` or `enabled`.

### `DELETE /api/v1/webhooks/{webhook_id}`

Delete the webhook.

---

## E2B Control Plane

The `/e2b` routes accept the official E2B SDKs and return native E2B objects (no `ApiResponse` wrapper).

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/e2b/sandboxes` | Create a sandbox from a template |
| `GET` | `/e2b/sandboxes/{id}` | Get sandbox state |
| `POST` | `/e2b/sandboxes/{id}/connect` | Resume a paused sandbox and set timeout |
| `POST` | `/e2b/sandboxes/{id}/pause` | Suspend (`memory: false` only) |
| `POST` | `/e2b/sandboxes/{id}/timeout` | Update timeout |
| `DELETE` | `/e2b/sandboxes/{id}` | Permanently delete |

Auth is `X-API-Key` (falling back to the orchestrator bearer token when `ORCHESTRATOR__E2B__API_KEY` is empty). Supported and unsupported E2B features are listed in the [E2B API Guide](../orchestrator/docs/API.md).

---

## Metrics

### `GET /metrics`

Prometheus scrape endpoint.

| Metric | Type | Labels |
|--------|------|--------|
| `litterbox_sandbox_create_duration_seconds` | Histogram | `template_id`, `success`, `source` |
| `litterbox_sandbox_create_total` | Counter | `template_id`, `success`, `source` |

`source` is `pool` or `direct`.

### `GET /api/v1/metrics/snapshot`

Returns the in-memory one-hour window as JSON, plus live sandbox counts.

```json
{
  "success": true,
  "data": {
    "window_seconds": 3600,
    "total": 42,
    "success": 41,
    "fail": 1,
    "success_rate": 0.9762,
    "p50_seconds": 0.38,
    "p90_seconds": 12.4,
    "live": { "total": 12, "running": 8, "stopped": 3, "creating": 1 },
    "by_template": {
      "ubuntu": { "total": 30, "success": 29, "fail": 1, "success_rate": 0.9667, "p50": 0.32, "p90": 8.1 }
    },
    "timeline": [
      { "minute_ago": 59, "count": 0, "success": 0, "fail": 0, "source_pool": 0, "source_direct": 0, "p50": null, "p90": null }
    ]
  }
}
```
