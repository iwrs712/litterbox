# Minimal E2B Control Plane Compatibility Design

## Goal

Allow an upstream service to use the official E2B Python SDK for the minimum sandbox lifecycle while preserving the existing Litterbox `/api/v1` contract.

## Scope

Implement a separate `/e2b` compatibility facade for:

- create sandbox
- get sandbox
- connect/resume sandbox
- pause sandbox with filesystem persistence (`keep_memory=false`)
- update timeout
- kill/delete sandbox

Reuse the existing `SandboxService`, `PoolService`, workspace PVC lifecycle, TTL queue, and envd proxy. Do not implement snapshots, fork, volumes, network policy, template build, traffic tokens, or memory snapshots in this phase.

## Protocol decisions

1. E2B routes are separate from `/api/v1` so existing dashboard and private clients remain unchanged.
2. E2B control responses use E2B-shaped JSON, not the existing `{success, data}` wrapper.
3. E2B API authentication accepts `X-API-Key`; the first implementation maps it to a configured orchestrator credential rather than adding a persistent key database.
4. Create translates E2B `templateID`, `envVars`, `timeout`, and `metadata` to existing Litterbox models.
5. `pause` maps to `suspend` and preserves the workspace PVC. `keep_memory=true` is rejected as unsupported.
6. `kill` maps to permanent Litterbox deletion and therefore deletes the workspace PVC and exposes.
7. The create response returns a per-sandbox envd domain. A host-based envd route will resolve `49983-{sandbox_id}.{sandbox_domain}` to the existing envd proxy.

## Minimum E2B routes

```text
POST   /e2b/sandboxes
GET    /e2b/sandboxes/{sandbox_id}
POST   /e2b/sandboxes/{sandbox_id}/connect
POST   /e2b/sandboxes/{sandbox_id}/pause
POST   /e2b/sandboxes/{sandbox_id}/timeout
DELETE /e2b/sandboxes/{sandbox_id}
```

The data-plane RPC paths remain envd-compatible and are routed by sandbox hostname. The existing path-based `/api/v1/sandboxes/{id}/envd/*` proxy remains available for private clients.

## Response mapping

The E2B create/connect response includes at least `sandboxID`, `domain`, `envdVersion`, and `envdAccessToken`. The adapter derives `domain` from configured sandbox base domain and the sandbox ID. No E2B response field claims memory snapshot support.

## Acceptance criteria

- Existing `/api/v1` tests remain green.
- E2B clients can create a sandbox, execute an envd command, connect to a stopped sandbox, and update its timeout.
- `pause(keep_memory=false)` retains workspace data.
- `kill()` removes the deployment, workspace PVC, and exposes.
- `pause(keep_memory=true)` returns a clear unsupported error.
- Invalid API keys are rejected without reaching sandbox services.
- E2B errors are returned in the expected non-wrapper shape.
- Host-based envd routing cannot address an arbitrary sandbox ID or arbitrary port.
