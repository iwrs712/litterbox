# agent-sandbox backend

The orchestrator runs on top of
[kubernetes-sigs/agent-sandbox](https://github.com/kubernetes-sigs/agent-sandbox)
v1.0.11 with the extensions controllers enabled.

## Objects

| Public concept | Kubernetes object |
| --- | --- |
| Template | `SandboxTemplate` (`extensions.agents.x-k8s.io/v1beta1`) |
| Warm pool | `SandboxWarmPool` (one per template; implicit zero-replica pools are hidden from the API) |
| Sandbox | `SandboxClaim`; the claim name is the public sandbox id |
| Pod | owned by the `Sandbox` created by the claim controller (or adopted from the warm pool) |

Templates and pools are materialized lazily by the orchestrator. The
`litterbox.io/implicit=true` annotation marks a zero-replica pool created only
so a cold claim has a `warmPoolRef`; it is removed when a real pool is created.

## Install

```bash
kubectl apply -f https://github.com/kubernetes-sigs/agent-sandbox/releases/download/v1.0.11/sandbox-with-extensions.yaml
kubectl apply -f deploy/agent-sandbox-rbac.yaml
```

Claim `additionalPodMetadata` labels use the `litterbox.io` domain. Allow it in
the extensions controller (read once at startup):

```bash
kubectl -n agent-sandbox-system create configmap agent-sandbox-config \
  --from-literal=allowed-label-domains=$'litterbox.io\nsandbox.users.io'
kubectl -n agent-sandbox-system rollout restart deploy/agent-sandbox-controller
```

## Semantics

- `/workspace` is an `emptyDir` with `sizeLimit` — sandboxes are disposable.
- TTL is `SandboxClaim.spec.lifecycle.shutdownTime`; expiry deletes the claim,
  sandbox and pod.
- Pause/resume maps to `Sandbox.spec.operatingMode`.
- The controller sets `automountServiceAccountToken: false` and the container
  carries an `ephemeral-storage` limit.
