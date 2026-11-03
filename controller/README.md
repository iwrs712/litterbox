# Litterbox sandbox controller

A Kubernetes controller that turns a `Sandbox` custom resource into a Pod and a
workspace PVC, and maintains warm `SandboxPool` supply. It is the sandbox
lifecycle implementation used by the Python orchestrator.

```text
orchestrator (API)                 controller                        Kubernetes
     │                                  │                                 │
     │ create/patch Sandbox CR ────────►│                                 │
     │ create/patch SandboxPool CR ────►│                                 │
     │                                  │ create/delete Pod + PVC ───────►│
     │◄────── read status.phase ────────│◄──── watch Pod/PVC events ──────│
```

The orchestrator never talks to Pods for lifecycle decisions. It writes
desired state (`spec.state`, `spec.ttlSeconds`, `spec.ttlAnchor`) and reads
`status.phase` / `status.podIP`. Pool allocation is an optimistic JSON Patch
claim against an `available` Sandbox, not a Redis lock.

## Why a controller

A request handler that creates a PVC and a workload, then polls readiness, can
fail halfway through and leave orphaned objects or a sandbox stuck in
`CREATING`. This controller is level-triggered instead:

| Concern | Imperative handler | Controller |
|---|---|---|
| Create | synchronous PVC + workload + readiness polling | one CR write; the controller converges asynchronously |
| Reads | list workloads on every request / dashboard refresh | informer cache, no API server read |
| TTL expiry | external queue + single-threaded worker | reconcile compares `ttlAnchor + ttlSeconds` with now |
| Crash recovery | no background repair | next reconcile repairs missing Pod/PVC |
| Cleanup | manual delete order | `ownerReference` garbage collection |
| Pod identity | workload + controller objects | Pod only |

## Reconciliation

For every `Sandbox` the controller ensures:

1. The workspace PVC exists (when `spec.workspace.enabled`).
2. The Pod exists and matches `spec` (the Pod carries a `litterbox.io/spec-hash`).
3. `status.phase` is one of `Pending`, `Running`, `Paused`, `Failed`.
4. `status.podIP` and `status.podName` point at the current Pod.
5. A suspended or expired sandbox has no Pod, but keeps its PVC.
6. Deleting the Sandbox deletes the Pod and PVC through `ownerReference`.

For every `SandboxPool` the controller ensures:

1. `available + creating` tracks `spec.targetReady`, capped by `spec.maxCreating`.
2. It creates Sandbox CRs with `pool-state=creating` and owns them through
   `ownerReference`.
3. A `creating` Sandbox becomes `available` once its `status.phase` is `Running`.
4. Excess `available` and all `failed` Sandboxes are deleted with a
   `resourceVersion` precondition, so a concurrent claim always wins.
5. An `allocated` Sandbox is detached from the pool. Deleting the pool never
   deletes a sandbox that a user is already using.
6. Pool status publishes `ready`, `creating`, `allocated`, `failed` and
   `terminating` counts.

The API claims an available sandbox with a JSON Patch that tests
`metadata.resourceVersion`; a lost race simply tries the next candidate.
There is no Redis pool lock and no Celery pool task.

A Pod that disappears (eviction, node loss, or `kubectl delete pod`) is
recreated on the next reconcile. Deleting the Sandbox never deletes the
workspace explicitly; garbage collection does it once the CR is gone.

## CRDs

See [config/crd.yaml](config/crd.yaml) for the full Sandbox schema and
[config/sandboxpool-crd.yaml](config/sandboxpool-crd.yaml) for SandboxPool.
A minimal SandboxPool:

```yaml
apiVersion: litterbox.io/v1alpha1
kind: SandboxPool
metadata:
  name: ubuntu
spec:
  templateID: ubuntu
  targetReady: 2
  maxCreating: 5
  sandboxTemplate:  # compiled by the orchestrator; cloned per sandbox
    templateID: ubuntu
    image: ubuntu:22.04
    resources: {limits: {cpu: 500m, memory: 512Mi}, requests: {cpu: 500m, memory: 512Mi}}
    workspace: {enabled: true, mountPath: /workspace, size: 1Gi, storageClassName: local-path, claimName: ""}
    envd: {enabled: true, hostBinaryPath: /opt/litterbox/bin/envd, containerBinaryPath: /opt/litterbox/envd/envd, port: 49983}
    lifecycle: {}
    state: Running
    ttlSeconds: 0
status:
  ready: 2
  creating: 0
  allocated: 0
```

The orchestrator compiles `sandboxTemplate` once when the pool is created.
The controller only rewrites the per-sandbox claim name and identity, then
creates a normal `Sandbox`. Pool sandboxes start without TTL; the TTL is set
when a sandbox is claimed.

`sandboxTemplate` is a snapshot. Update the template and recreate the pool if
the pool should use a new image, command or resource shape.

A minimal Sandbox:

```yaml
apiVersion: litterbox.io/v1alpha1
kind: Sandbox
metadata:
  name: abc12345
  labels:
    component: sandbox
    litterbox.io/template-id: ubuntu
spec:
  templateID: ubuntu
  image: ubuntu:22.04
  command: ["sleep", "infinity"]
  resources:
    limits: {cpu: 500m, memory: 512Mi}
    requests: {cpu: 500m, memory: 512Mi}
  workspace:
    enabled: true
    mountPath: /workspace
    size: 1Gi
    storageClassName: local-path
    claimName: workspace-abc12345
  envd:
    enabled: true
    hostBinaryPath: /opt/litterbox/bin/envd
    containerBinaryPath: /opt/litterbox/envd/envd
    port: 49983
  lifecycle:
    postStart: ["/opt/litterbox/envd/envd", "daemon", "--host", "0.0.0.0", "--port", "49983", "--filesystem-root", "/"]
  state: Running
  ttlSeconds: 600
  ttlAnchor: "2026-11-03T10:00:00Z"
status:
  phase: Running
  podName: abc12345
  podIP: 10.42.0.9
```

`state: Paused` or an expired TTL leaves the PVC intact and removes the Pod.
`ttlAnchor` is reset by the orchestrator on resume / `set_timeout`.

## Install

```bash
kubectl apply -f config/crd.yaml
kubectl apply -f config/sandboxpool-crd.yaml
kubectl apply -f config/rbac.yaml
kubectl apply -f config/controller.yaml
```

The manifests assume the controller and the orchestrator run in namespace
`litterbox`. Adjust the ServiceAccounts/bindings for your environment.

The orchestrator uses this API unconditionally. CRD coordinates can be
overridden if needed:

```toml
[sandbox]
# crd_group = "litterbox.io"
# crd_version = "v1alpha1"
# crd_plural = "sandboxes"
```

## Build and test

```bash
go test ./...

# Multi-arch container image
docker build --build-arg TARGETARCH=arm64 -t litterbox/sandbox-controller:local .

# Fast path for k3d / local clusters
CGO_ENABLED=0 GOOS=linux GOARCH=arm64 \
  go build -trimpath -ldflags='-s -w' -o bin/controller-linux-arm64 ./cmd/controller
docker build -f Dockerfile.cross \
  --build-arg BINARY=bin/controller-linux-arm64 \
  -t litterbox/sandbox-controller:local .
k3d image import litterbox/sandbox-controller:local -c litterbox
```

## Operations

- **Leader election** is enabled by default (`--leader-elect=true`). Scale
  replicas safely; only one instance reconciles at a time.
- **Workers** default to 4. Reconcile is idempotent, so raising this is safe.
- **Health** is exposed on `:8090` (`/healthz`, `/readyz`).
- **Namespace scope** is all namespaces. The Pod and PVC are created in the
  Sandbox's namespace.
- **RuntimeClass / envd** are copied from the CR spec. The orchestrator only
  sets a RuntimeClass when it exists in the cluster.
- **Image pull policy** defaults to `IfNotPresent` when `spec.imagePullPolicy`
  is empty, so locally imported images work without registry access. Set the
  field explicitly to `Always` if every sandbox must re-resolve its tag.
- **Pool allocation** is a JSON Patch claim on `metadata.resourceVersion`.
  There is no global lock; conflicting claims retry the next sandbox.
- **Pool deletion** garbage-collects `creating` / `available` / `failed`
  sandboxes. An `allocated` sandbox is detached at claim time and survives.

## E2E

`e2e/e2b_crd_e2e.py` exercises the path end to end through the official E2B
SDK: create, exec, file I/O, pod self-healing, pause/resume, TTL expiry,
workspace persistence and kill. It also asserts the CR status and Kubernetes
objects. See the script header for the required environment variables.

`e2e/pool_crd_e2e.py` exercises warm-pool provisioning, optimistic claim,
replenishment, and the guarantee that deleting a pool does not delete an
already allocated sandbox.
