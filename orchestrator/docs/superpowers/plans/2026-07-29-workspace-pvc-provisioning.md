# Workspace PVC Provisioning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provision one persistent workspace PVC per newly created sandbox and mount it at `/workspace` in a Dragonball-backed Pod.

**Architecture:** A `WorkspaceConfig` supplies a cluster-wide default requested capacity while retaining the existing configurable Kubernetes storage class. `SandboxService` deterministically derives `workspace-{sandbox_id}`, creates that PVC before the Deployment, and mounts the claim into the Pod template. If creating the Deployment fails, it removes the just-created claim because no sandbox exists to own it.

**Tech Stack:** Python 3.12, Pydantic, Kubernetes Python client, pytest, K3s local-path storage, Kata Dragonball.

---

## Scope

This plan is the first independently deployable phase. It deliberately excludes suspend/resume endpoints, TTL suspension, permanent deletion of workspace PVCs, and dashboard changes; those lifecycle semantics are covered by the approved design and will be implemented in a second plan after provisioning is working.

## File Map

- Modify: `config.toml` - select Dragonball and configure the default workspace capacity.
- Modify: `src/orchestrator/config.py` - load the workspace capacity setting.
- Modify: `src/orchestrator/infra/kubernetes.py` - create and delete namespaced PVCs.
- Modify: `src/orchestrator/services/sandboxes.py` - build the PVC, create it before the Deployment, and mount it at `/workspace`.
- Modify: `tests/test_sandbox_lifecycle.py` - assert the generated Pod template mounts the deterministic claim.
- Create: `tests/test_workspace_pvc_provisioning.py` - verify creation ordering and rollback behavior.
- Modify: `ARCHITECTURE.md` - document the new Deployment/PVC persistence topology.

### Task 1: Add Workspace Configuration And Select Dragonball

**Files:**
- Modify: `src/orchestrator/config.py:17-61`
- Modify: `config.toml:5-15`
- Test: `tests/test_workspace_pvc_provisioning.py`

- [ ] **Step 1: Write the failing configuration test**

```python
from orchestrator.config import Settings


def test_workspace_default_size_is_one_gib() -> None:
    assert Settings().workspace.default_size == "1Gi"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_workspace_pvc_provisioning.py::test_workspace_default_size_is_one_gib -v`

Expected: FAIL because `Settings` has no `workspace` attribute.

- [ ] **Step 3: Add the configuration model and TOML values**

Add this model after `SandboxConfig`:

```python
class WorkspaceConfig(BaseModel):
    default_size: str = "1Gi"
```

Add it to `Settings`:

```python
workspace: WorkspaceConfig = Field(default_factory=WorkspaceConfig)
```

Change the runtime and add the workspace section in `config.toml`:

```toml
[kubernetes]
runtime_class = "kata-dragonball"
storage_class = "local-path"

[workspace]
default_size = "1Gi"
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_workspace_pvc_provisioning.py::test_workspace_default_size_is_one_gib -v`

Expected: PASS.

- [ ] **Step 5: Commit the configuration change**

```bash
git add config.toml src/orchestrator/config.py tests/test_workspace_pvc_provisioning.py
git commit -m "feat: configure Dragonball workspaces"
```

### Task 2: Mount The Deterministic Workspace Claim

**Files:**
- Modify: `src/orchestrator/services/sandboxes.py:314-437`
- Modify: `tests/test_sandbox_lifecycle.py:42-69`

- [ ] **Step 1: Write the failing Pod-template test**

Add this test using the existing `build_service()` and `build_template()` helpers:

```python
def test_build_deployment_mounts_workspace_pvc() -> None:
    service = build_service()
    deployment = service._build_deployment(
        sandbox_id="sbx-workspace",
        template=build_template(),
        metadata={},
        name="",
        env=None,
        pool_state="none",
        ttl_seconds=None,
    )

    pod_spec = deployment.spec.template.spec
    volumes = {volume.name: volume for volume in pod_spec.volumes or []}
    mounts = {mount.name: mount for mount in pod_spec.containers[0].volume_mounts or []}

    assert volumes["workspace"].persistent_volume_claim.claim_name == "workspace-sbx-workspace"
    assert mounts["workspace"].mount_path == "/workspace"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_sandbox_lifecycle.py::test_build_deployment_mounts_workspace_pvc -v`

Expected: FAIL with no `workspace` volume.

- [ ] **Step 3: Add a workspace-claim naming helper and append the volume**

Add a helper to `SandboxService`:

```python
@staticmethod
def _workspace_claim_name(sandbox_id: str) -> str:
    return f"workspace-{sandbox_id}"
```

At the start of the existing `volume_mounts` and `volumes` setup in `_build_deployment`, initialize both with the persistent workspace volume:

```python
workspace_claim_name = self._workspace_claim_name(sandbox_id)
volume_mounts = [client.V1VolumeMount(name="workspace", mount_path="/workspace")]
volumes = [
    client.V1Volume(
        name="workspace",
        persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
            claim_name=workspace_claim_name,
        ),
    )
]
```

Keep the existing `host_path_mounts` loop so host mounts remain additive.

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_sandbox_lifecycle.py::test_build_deployment_mounts_workspace_pvc -v`

Expected: PASS.

- [ ] **Step 5: Run the sandbox template test module**

Run: `pytest tests/test_sandbox_lifecycle.py tests/test_sandbox_env_overrides.py -v`

Expected: PASS.

- [ ] **Step 6: Commit the mount template change**

```bash
git add src/orchestrator/services/sandboxes.py tests/test_sandbox_lifecycle.py
git commit -m "feat: mount workspace PVC in sandbox pods"
```

### Task 3: Provision The Claim Before Creating The Deployment

**Files:**
- Modify: `src/orchestrator/infra/kubernetes.py:50-107`
- Modify: `src/orchestrator/services/sandboxes.py:55-102`
- Create: `tests/test_workspace_pvc_provisioning.py`


- [ ] **Step 1: Write the failing creation-order test and its recording fixture**

Replace `tests/test_workspace_pvc_provisioning.py` with this complete final content, preserving the configuration assertion from Task 1:

```python
from __future__ import annotations

from types import SimpleNamespace

import pytest

from orchestrator.config import Settings
from orchestrator.domain.models import Template, utcnow
from orchestrator.services.sandboxes import SandboxService


def test_workspace_default_size_is_one_gib() -> None:
    assert Settings().workspace.default_size == "1Gi"


class RecordingGateway:
    namespace = "default"
    available_runtime_classes: set[str] = set()

    def __init__(self, *, fail_deployment: bool = False) -> None:
        self.events: list[str] = []
        self.fail_deployment = fail_deployment
        self.created_claim = None

    def secret_exists(self, _name: str) -> bool:
        return False

    def create_persistent_volume_claim(self, claim) -> None:
        self.events.append("pvc")
        self.created_claim = claim

    def create_deployment(self, _deployment) -> None:
        self.events.append("deployment")
        if self.fail_deployment:
            raise RuntimeError("deployment create failed")

    def delete_persistent_volume_claim(self, _name: str) -> None:
        self.events.append("delete-pvc")


def build_provisioning_service(
    *,
    fail_deployment: bool = False,
) -> tuple[SandboxService, RecordingGateway]:
    now = utcnow()
    template = Template(
        id="tpl-workspace",
        name="Workspace template",
        image="busybox:1.37",
        cpu_millicores=100,
        memory_mb=128,
        created_at=now,
        updated_at=now,
    )
    gateway = RecordingGateway(fail_deployment=fail_deployment)
    settings = Settings.model_validate(
        {
            "kubernetes": {"storage_class": "local-path"},
            "workspace": {"default_size": "1Gi"},
        }
    )
    service = SandboxService(
        gateway=gateway,
        template_service=SimpleNamespace(get_template=lambda _template_id: template),
        webhook_dispatcher=SimpleNamespace(),
        ttl_queue=SimpleNamespace(),
        settings=settings,
    )
    service.get_sandbox = lambda sandbox_id: SimpleNamespace(id=sandbox_id)
    return service, gateway


def test_create_sandbox_creates_workspace_pvc_before_deployment() -> None:
    service, gateway = build_provisioning_service()

    service.create_sandbox(
        template_id="tpl-workspace",
        wait_ready=False,
        dispatch_events=False,
    )

    assert gateway.events == ["pvc", "deployment"]
    claim = gateway.created_claim
    assert claim.metadata.name.startswith("workspace-")
    assert claim.spec.access_modes == ["ReadWriteOnce"]
    assert claim.spec.volume_mode == "Filesystem"
    assert claim.spec.storage_class_name == "local-path"
    assert claim.spec.resources.requests == {"storage": "1Gi"}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_workspace_pvc_provisioning.py::test_create_sandbox_creates_workspace_pvc_before_deployment -v`

Expected: FAIL because sandbox creation only records the Deployment and never calls `create_persistent_volume_claim()`.

- [ ] **Step 3: Add Kubernetes Gateway PVC methods**

Add these methods next to the existing ConfigMap methods:

```python
def create_persistent_volume_claim(
    self,
    claim: client.V1PersistentVolumeClaim,
) -> client.V1PersistentVolumeClaim:
    return self.core.create_namespaced_persistent_volume_claim(self.namespace, claim)

def delete_persistent_volume_claim(self, name: str) -> None:
    try:
        self.core.delete_namespaced_persistent_volume_claim(name, self.namespace)
    except ApiException as exc:
        if exc.status != 404:
            raise
```


- [ ] **Step 4: Build and create the PVC before the Deployment**

Add `_build_workspace_claim()` to `SandboxService`:

```python
def _build_workspace_claim(self, sandbox_id: str) -> client.V1PersistentVolumeClaim:
    return client.V1PersistentVolumeClaim(
        metadata=client.V1ObjectMeta(
            name=self._workspace_claim_name(sandbox_id),
            namespace=self.gateway.namespace,
            labels={
                "app": "litterbox",
                "component": "workspace",
                "litterbox.io/sandbox-id": sandbox_id,
            },
        ),
        spec=client.V1PersistentVolumeClaimSpec(
            access_modes=["ReadWriteOnce"],
            volume_mode="Filesystem",
            storage_class_name=self.settings.kubernetes.storage_class or None,
            resources=client.V1ResourceRequirements(
                requests={"storage": self.settings.workspace.default_size},
            ),
        ),
    )
```

In `create_sandbox()`, create the claim immediately before `create_deployment()`:

```python
workspace_claim = self._build_workspace_claim(sandbox_id)
self.gateway.create_persistent_volume_claim(workspace_claim)
self.gateway.create_deployment(deployment)
```

- [ ] **Step 5: Run the creation-order test to verify it passes**

Run: `pytest tests/test_workspace_pvc_provisioning.py::test_create_sandbox_creates_workspace_pvc_before_deployment -v`

Expected: PASS.


- [ ] **Step 6: Write the failing rollback test**

Use the same recording gateway but have `create_deployment()` raise `RuntimeError("deployment create failed")`.

```python
def test_create_sandbox_deletes_new_workspace_pvc_when_deployment_creation_fails() -> None:
    service, gateway = build_provisioning_service(fail_deployment=True)

    with pytest.raises(RuntimeError, match="deployment create failed"):
        service.create_sandbox(
            template_id="tpl-workspace",
            wait_ready=False,
            dispatch_events=False,
        )

    assert gateway.events == ["pvc", "deployment", "delete-pvc"]
```

- [ ] **Step 7: Run the rollback test to verify it fails**

Run: `pytest tests/test_workspace_pvc_provisioning.py::test_create_sandbox_deletes_new_workspace_pvc_when_deployment_creation_fails -v`

Expected: FAIL until the rollback block exists.


- [ ] **Step 8: Add rollback when Deployment creation fails**

Replace the direct Deployment creation with this bounded rollback:

```python
workspace_claim = self._build_workspace_claim(sandbox_id)
self.gateway.create_persistent_volume_claim(workspace_claim)
try:
    self.gateway.create_deployment(deployment)
except Exception:
    self.gateway.delete_persistent_volume_claim(workspace_claim.metadata.name)
    raise
```

- [ ] **Step 9: Run focused tests after the rollback implementation**

Run: `pytest tests/test_workspace_pvc_provisioning.py tests/test_sandbox_lifecycle.py tests/test_sandbox_env_overrides.py -v`

Expected: PASS.


- [ ] **Step 10: Commit provisioning behavior**

```bash
git add src/orchestrator/infra/kubernetes.py src/orchestrator/services/sandboxes.py tests/test_workspace_pvc_provisioning.py
git commit -m "feat: provision workspace PVCs for sandboxes"
```

### Task 4: Document And Validate The First Phase

**Files:**
- Modify: `ARCHITECTURE.md:215-230`
- Test: `tests/test_workspace_pvc_provisioning.py`

- [ ] **Step 1: Document the PVC in the Kubernetes persistence model**

Add this entry under the Kubernetes resource list:

```markdown
- `PersistentVolumeClaim`
  one durable `/workspace` filesystem per sandbox; created before its Deployment
```

Update the direct allocation flow to include:

```text
-> workspace PVC created
-> Kubernetes Deployment created with the PVC mounted at /workspace
```

- [ ] **Step 2: Run the complete test suite**

Run: `pytest -v`

Expected: PASS.

- [ ] **Step 3: Run static checks**

Run: `ruff check src tests`

Expected: PASS.

- [ ] **Step 4: Verify the server smoke resources**

Run on the K3s host:

```bash
kubectl get pvc workspace-kata-dragonball-pvc-smoke -n default
kubectl exec -n default deployment/kata-dragonball-pvc-smoke -- cat /workspace/persistence-proof
```

Expected: the PVC is `Bound` and the proof file remains after Pod recreation.

- [ ] **Step 5: Commit documentation**

```bash
git add ARCHITECTURE.md
git commit -m "docs: describe persistent sandbox workspaces"
```
