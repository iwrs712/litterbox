# Minimal E2B Control Plane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a minimal `/e2b` compatibility facade so the official E2B Python SDK can create, inspect, connect, pause, timeout, and delete Litterbox sandboxes.

**Architecture:** Keep `/api/v1` unchanged. Add E2B-shaped request/response models and an adapter service that delegates to existing `PoolService`/`SandboxService`. Add E2B API-key authentication and a host-based envd entrypoint so SDK data-plane requests can reach the existing envd proxy.

**Tech Stack:** FastAPI, Pydantic v2, Kubernetes gateway, existing envd HTTP proxy, pytest/TestClient.

---

### Task 1: Add E2B protocol models and adapter mapping

**Files:**
- Create: `src/orchestrator/domain/e2b_models.py`
- Create: `src/orchestrator/services/e2b.py`
- Test: `tests/test_e2b_control_plane.py`

- [ ] Write tests for E2B create field conversion, response field shape, and timeout/pause/delete delegation.
- [ ] Run the focused tests and confirm they fail because the adapter does not exist.
- [ ] Implement models with camelCase E2B fields and an adapter that delegates to existing services.
- [ ] Run the focused tests and confirm they pass.

### Task 2: Add E2B routes and API-key authentication

**Files:**
- Create: `src/orchestrator/routes/e2b.py`
- Modify: `src/orchestrator/main.py`
- Modify: `src/orchestrator/auth.py`
- Modify: `src/orchestrator/config.py`
- Test: `tests/test_e2b_control_plane.py`
- Test: `tests/test_api_bearer_auth.py`

- [ ] Add `/e2b/sandboxes` create/get/connect/pause/timeout/delete routes.
- [ ] Accept `X-API-Key` for `/e2b/*`; keep Bearer behavior for `/api/v1/*`.
- [ ] Return E2B errors directly instead of `{success, data}` wrappers.
- [ ] Map `connect` to resume, `pause` to filesystem-only suspend, `timeout` to current TTL update, and delete to permanent cleanup.
- [ ] Return `409` for `keep_memory=true` because memory snapshots are not implemented.
- [ ] Run focused auth and route tests.

### Task 3: Add hostname-based envd routing

**Files:**
- Modify: `src/orchestrator/routes/envd.py`
- Modify: `src/orchestrator/services/envd_proxy.py`
- Modify: `src/orchestrator/config.py`
- Create: `tests/test_e2b_envd_host_routing.py`

- [ ] Test parsing `49983-{sandbox_id}.{domain}` and rejecting unknown ports/hosts.
- [ ] Route the request path without `/api/v1/.../envd` through the existing proxy.
- [ ] Return the configured sandbox domain in E2B create/connect responses.
- [ ] Keep the existing path-based envd route unchanged.

### Task 4: Verify SDK-facing contract and update documentation

**Files:**
- Modify: `docs/API.md`
- Test: `tests/test_e2b_control_plane.py`

- [ ] Add SDK-facing curl/Python examples using `/e2b` and `X-API-Key`.
- [ ] Document `pause(keep_memory=False)` and the destructive behavior of `kill()`.
- [ ] Run the focused E2B tests, existing auth/envd tests, and full pytest suite.
- [ ] Run `git diff --check` and report any remaining OpenAPI warnings separately.
