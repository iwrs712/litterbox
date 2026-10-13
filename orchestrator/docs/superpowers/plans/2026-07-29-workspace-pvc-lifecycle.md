# Workspace PVC Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve a sandbox workspace through suspend, resume, and TTL expiry, while permanent deletion removes all resources including its PVC.

**Architecture:** The sandbox service owns lifecycle transitions: scale an existing Deployment to zero for suspension, scale it to one and wait for readiness for resumption, and preserve the PVC in both paths. The TTL worker enters the same suspension path, clears its one-shot active schedule, and resumption derives a new schedule from the stored positive TTL. The Kubernetes gateway exposes a typed no-running-pod error so HTTP routes can return a stable `409` response for stopped sandboxes.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, Kubernetes Python client, pytest.

---

### Task 1: Add Service Lifecycle Tests

**Files:**
- Create: `tests/test_sandbox_suspension.py`
- Modify: `tests/test_sandbox_lifecycle.py` (only the sandbox-delete doubles)

- [ ] **Step 1: Write failing service tests**

```python
def test_suspend_scales_deployment_to_zero_without_deleting_workspace_pvc():
    service, gateway = build_service(replicas=1)

    response = service.suspend_sandbox("sbx-1")

    assert response.status == SandboxStatus.STOPPED
    assert gateway.scale_calls == [("sbx-1", 0)]
    assert gateway.deleted_claims == []


def test_resume_scales_to_one_and_waits_for_workspace_pod():
    service, gateway = build_service(replicas=0)

    service.resume_sandbox("sbx-1")

    assert gateway.scale_calls == [("sbx-1", 1)]
    assert gateway.ready_selectors == ["app=sbx-1,component=sandbox"]
```

- [ ] **Step 2: Run the focused tests and verify failure**

Run: `pytest tests/test_sandbox_suspension.py -v`

Expected: FAIL because `SandboxService` has no `suspend_sandbox` or `resume_sandbox` method.

- [ ] **Step 3: Test permanent deletion of the PVC**

```python
service.delete_sandbox("sbx-1")

assert gateway.deleted_claims == ["workspace-sbx-1"]
```

- [ ] **Step 4: Run the delete test and verify failure**

Run: `pytest tests/test_sandbox_lifecycle.py -v`

Expected: FAIL because `delete_sandbox` does not delete the workspace claim.

- [ ] **Step 5: Implement minimal lifecycle methods**

```python
def suspend_sandbox(self, sandbox_id: str, *, ttl_expired: bool = False) -> SandboxResponse:
    deployment = self.gateway.read_deployment(sandbox_id)
    if (deployment.spec.replicas or 0) != 0:
        self.gateway.scale_deployment(sandbox_id, 0)
    if ttl_expired:
        self._clear_active_ttl_schedule(sandbox_id, annotations)
    return self.get_sandbox(sandbox_id)

def resume_sandbox(self, sandbox_id: str) -> SandboxResponse:
    deployment = self.gateway.read_deployment(sandbox_id)
    self._rearm_ttl_after_suspension(sandbox_id, annotations)
    if (deployment.spec.replicas or 0) == 0:
        self.gateway.scale_deployment(sandbox_id, 1)
        self.gateway.wait_for_pod_ready(f"app={sandbox_id},component=sandbox")
    return self.get_sandbox(sandbox_id)
```

Call `delete_persistent_volume_claim(self._workspace_claim_name(sandbox_id))` after deleting the Deployment. Do not delete claims from suspend or resume.

- [ ] **Step 6: Run service lifecycle tests**

Run: `pytest tests/test_sandbox_lifecycle.py tests/test_sandbox_suspension.py -v`

Expected: PASS.

### Task 2: Make TTL Expiry Suspend and Resume Re-arm TTL

**Files:**
- Modify: `src/orchestrator/services/sandboxes.py`
- Modify: `tests/test_sandbox_suspension.py`

- [ ] **Step 1: Write failing TTL tests**

```python
assert service.delete_if_ttl_due("sbx-1", "ttl-old") is True
assert gateway.scale_calls == [("sbx-1", 0)]
assert gateway.deleted_claims == []
assert "litterbox.io/expires-at" not in gateway.annotations
assert gateway.unscheduled == [TTLEntry(sandbox_id="sbx-1", ttl_token="ttl-old")]

service.resume_sandbox("sbx-1")
assert "litterbox.io/expires-at" in gateway.annotations
assert gateway.scheduled[0].sandbox_id == "sbx-1"
```

- [ ] **Step 2: Run the focused TTL tests and verify failure**

Run: `pytest tests/test_sandbox_suspension.py -k ttl -v`

Expected: FAIL because expiry still deletes the Deployment and resumption does not re-arm a TTL.

- [ ] **Step 3: Implement TTL suspension transitions**

On TTL expiry, retain `litterbox.io/ttl-seconds`, remove `expires-at`, `ttl-token`, and `last-ttl-renewal`, set `litterbox.io/ttl-suspended-at`, patch annotations, and unschedule the consumed token. Use this flow from both `cleanup_expired` and `delete_if_ttl_due`. During resume, only when the TTL-suspended marker exists and the retained TTL is positive, generate a fresh token and expiry, remove the marker, patch the annotations, and schedule the new entry.

- [ ] **Step 4: Ensure disabling or rearming TTL clears the marker**

```python
def _set_ttl_annotations(...):
    annotations.pop("litterbox.io/ttl-suspended-at", None)

def _clear_ttl_annotations(...):
    annotations.pop("litterbox.io/ttl-suspended-at", None)
```

- [ ] **Step 5: Run the TTL and lifecycle tests**

Run: `pytest tests/test_sandbox_suspension.py tests/test_sandbox_lifecycle.py -v`

Expected: PASS.

### Task 3: Return Conflict for Stopped Sandbox Operations

**Files:**
- Modify: `src/orchestrator/infra/kubernetes.py`
- Modify: `src/orchestrator/routes/sandboxes.py`
- Modify: `tests/test_sandbox_suspension.py`

- [ ] **Step 1: Write failing gateway and route tests**

```python
with pytest.raises(SandboxNotRunningError):
    gateway.get_first_running_pod("sbx-stopped")

response = client.post("/api/v1/sandboxes/sbx-stopped/exec", json={"command": ["pwd"]})
assert response.status_code == 409
```

Repeat the `409` assertion for file GET, PUT, and DELETE operations.

- [ ] **Step 2: Run these tests and verify failure**

Run: `pytest tests/test_sandbox_suspension.py -k 'not ttl' -v`

Expected: FAIL because stopped Pod lookup raises `RuntimeError` and routes return `500`.

- [ ] **Step 3: Implement the typed error and route mapping**

```python
class SandboxNotRunningError(RuntimeError):
    pass

raise SandboxNotRunningError(f"sandbox {sandbox_id} is not running")
```

Import the exception in `routes/sandboxes.py` and catch it before generic exceptions in exec and every file handler, returning `error(str(exc), 409)`.

- [ ] **Step 4: Run the conflict tests**

Run: `pytest tests/test_sandbox_suspension.py -k conflict -v`

Expected: PASS.

### Task 4: Verify the Complete Lifecycle

**Files:**
- Modify: `docs/superpowers/plans/2026-07-29-workspace-pvc-lifecycle.md`

- [ ] **Step 1: Run the relevant non-integration test suite**

Run: `pytest --ignore=tests/integration -v`

Expected: PASS. Do not run integration tests with the current local cluster configuration because they may create live Kubernetes resources.

- [ ] **Step 2: Compile sources**

Run: `python3 -m compileall -q src`

Expected: exit code 0.

- [ ] **Step 3: Inspect the staged diff before committing**

Run: `git diff --check && git diff --cached --check && git status --short`

Expected: no whitespace errors; stage only the lifecycle service, gateway, route, and new test/doc changes, preserving user-owned dashboard, TTL validation, pool, and existing lifecycle test changes.

- [ ] **Step 4: Commit only lifecycle-owned files**

```bash
git add src/orchestrator/services/sandboxes.py src/orchestrator/infra/kubernetes.py src/orchestrator/routes/sandboxes.py tests/test_sandbox_suspension.py docs/superpowers/plans/2026-07-29-workspace-pvc-lifecycle.md
git commit -m "feat: suspend sandboxes while preserving workspaces"
```
