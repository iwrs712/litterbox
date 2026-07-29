# Workspace PVC And Sandbox Suspension Design

## Goal

Each sandbox owns a persistent workspace mounted at `/workspace`. Suspending a
sandbox releases its runtime resources without removing its files. Permanently
deleting a sandbox removes the workspace and every Kubernetes resource owned by
that sandbox.

## Resource Model

For a sandbox with ID `sbx-123`, the orchestrator creates a PVC named
`workspace-sbx-123` before creating its Deployment.

The PVC has these properties:

- `ReadWriteOnce` access mode
- `Filesystem` volume mode
- Storage class from `kubernetes.storage_class`
- Requested capacity from `workspace.default_size`, initially `1Gi`
- Labels identifying the sandbox and the workspace component
- No owner reference to the Deployment or its Pods

The Deployment mounts this PVC at `/workspace`. Its container root filesystem
remains ephemeral. Existing sandboxes are not mutated; the feature applies to
sandboxes created after deployment of this change.

## Lifecycle API

`DELETE /sandboxes/{id}` remains a permanent deletion operation. It removes
the sandbox Deployment, its expose resources, and `workspace-{id}`. The
workspace storage class must use `reclaimPolicy: Delete` when permanent
deletion must erase the backing data. The current `local-path` storage class
has that policy.

`POST /sandboxes/{id}/suspend` scales the Deployment to zero. It retains the
PVC, Service, Ingress, and sandbox Deployment metadata. This preserves the
workspace and its stable endpoints for later recovery.

`POST /sandboxes/{id}/resume` scales the existing Deployment back to one,
waits for a ready Pod, and returns the running sandbox. Kubernetes attaches
the same PVC, so the new runtime sees the original `/workspace` files.

Both suspend and resume are idempotent. A suspend request for an already
stopped sandbox succeeds, as does a resume request for an already running
sandbox.

## TTL Behavior

TTL expiry invokes the same suspension flow rather than permanent deletion.
The service records that TTL has suspended the sandbox and clears the active
expiry schedule, preventing the TTL worker from repeatedly acting on the same
sandbox.

Resuming a sandbox suspended by TTL re-arms its existing positive TTL from the
resume time. A sandbox with TTL set to zero remains unscheduled. Callers can
set TTL to zero before resuming when the resumed sandbox must not expire.

Manual suspension does not alter an active TTL. Its expiry can still suspend
the already stopped Deployment idempotently.

## Runtime And Error Semantics

While suspended, terminal, command, and workspace file endpoints return HTTP
409 because no running Pod exists. The caller resumes the sandbox before
retrying the operation.

Service and Ingress objects remain during suspension. They have no ready
backend until the Deployment is resumed, then recover their original routing
without recreating their configuration.

## Implementation Boundaries

The Kubernetes gateway gains PVC create/read/delete operations. Sandbox
creation creates the workspace claim before the Deployment. If Deployment
creation fails, the newly created claim is removed because no sandbox was
created to own it.

The initial feature does not introduce per-template workspace sizing, restore
after permanent deletion, storage snapshots, or hard quota enforcement. A
block-capable CSI backend can later replace `local-path` without changing the
sandbox-to-PVC contract.

## Verification

Automated tests cover PVC creation before Deployment creation, PVC fields,
Deployment mounting at `/workspace`, no PVC deletion during suspension or TTL
expiry, PVC deletion during permanent deletion, idempotent suspend/resume,
and TTL re-arming after resume.
