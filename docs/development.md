# Development Guide

This guide covers setting up a local development environment for both the backend and frontend.

---

## Backend (`orchestrator/`)

### Setup

```bash
cd orchestrator
uv sync --extra dev
```

### Configure

```bash
cp config.example.toml config.toml
```

Then edit `config.toml` (or override individual keys with `ORCHESTRATOR__*` variables):

```toml
[kubernetes]
kubeconfig = "/home/youruser/.kube/config"
namespace  = "litterbox-dev"

[celery]
broker_url     = "redis://localhost:6379/2"
result_backend = "redis://localhost:6379/2"
```

```bash
export ORCHESTRATOR__KUBERNETES__KUBECONFIG=/home/youruser/.kube/config
export ORCHESTRATOR__KUBERNETES__NAMESPACE=litterbox-dev
```

### Run Services

Each process runs in a separate terminal.

**API server:**
```bash
uv run uvicorn orchestrator.main:app --reload --port 8080
# Interactive docs: http://localhost:8080/docs
```

**Celery worker** (webhook delivery):
```bash
uv run celery -A orchestrator.celery_app:celery_app worker \
  -l info \
  -Q webhook_delivery \
  -n worker@%h
```

**Sandbox controller** (Go, required for every sandbox and pool):
```bash
cd ../controller
go run ./cmd/controller --leader-elect=false --kubeconfig ~/.kube/config
```
In a cluster, apply `controller/config/crd.yaml`,
`controller/config/sandboxpool-crd.yaml`, `controller/config/rbac.yaml` and
`controller/config/controller.yaml` instead.

> **Tip:** Use [tmux](https://github.com/tmux/tmux/wiki) or [overmind](https://github.com/DarthSim/overmind) to manage multiple terminals conveniently.

### Run Tests

```bash
# All tests (requires a real K8s cluster + Redis)
pytest

# Unit tests only (no cluster needed)
pytest tests/ -k "not integration"

# Integration tests
pytest tests/integration/

# With coverage
pytest --cov=orchestrator --cov-report=term-missing
```

> **Warning:** Integration tests create real Kubernetes resources. Point your `kubeconfig` at a local dev cluster (kind/k3s), never production.

### Code Structure

```
orchestrator/src/orchestrator/
├── domain/
│   ├── models.py          # Pydantic v2 models (Template, Sandbox, Pool, Webhook…)
│   └── e2b_models.py      # E2B-compatible request/response models
├── infra/
│   ├── kubernetes.py      # KubernetesGateway — Pods, Services, Ingresses, ConfigMaps
│   ├── sandbox_crd.py     # Dynamic client for Sandbox custom resources
│   ├── sandbox_pool_crd.py# SandboxPool repository
│   └── repositories.py    # ConfigMap-backed repos (TemplateRepo, WebhookRepo)
├── routes/                # HTTP transports
│   ├── templates.py
│   ├── sandboxes.py
│   ├── pools.py
│   ├── exposes.py
│   ├── webhooks.py
│   ├── metrics.py
│   ├── envd.py            # envd path proxy + E2B wildcard host routing
│   └── e2b.py             # E2B control plane
├── services/
│   ├── sandboxes.py       # Sandbox CR lifecycle business logic
│   ├── sandbox_crd.py     # CR spec compilation + status projection
│   ├── pools.py           # Pool management + reconcile loop
│   ├── templates.py       # Template CRUD
│   ├── webhooks.py        # Webhook delivery
│   ├── envd_proxy.py      # Authenticated proxy to the sandbox envd process
│   ├── e2b.py             # E2B control-plane adapter
│   ├── exposes.py         # Service/Ingress expose management
│   └── metrics.py         # Prometheus + in-memory snapshot
├── container.py           # Dependency injection — wires all services together
├── main.py                # FastAPI app, middleware and router wiring
├── tasks.py               # Celery task definitions
├── celery_app.py          # Celery app instance
├── config.py              # Settings model (TOML + env vars)
├── auth.py                # Bearer and E2B API-key checks
└── utils.py               # Shared utilities (short_id, label sanitization…)
```

---

## Frontend (`dashboard/`)

### Setup

```bash
cd dashboard
npm install          # or: pnpm install
```

### Run

```bash
npm run dev:local
# http://localhost:5173

# Type-check only (no emit)
npm run check

# Production build → dist/ (runs `buf generate` first)
npm run build

# Preview production build locally
npm run preview
```

> `dev:local` creates `.env.local` from `.env.local.example` and points the dashboard at `http://127.0.0.1:8080` by default.
>
> The dashboard contains generated envd protobuf clients. `npm run build` regenerates them with `buf`; run `npm run generate:envd` after changing the proto definitions.


