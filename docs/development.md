# Development Guide

This guide covers setting up a local development environment for both the backend and frontend.

---

## Backend (`orchestrator/`)

### Setup

```bash
cd orchestrator

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# Install with dev dependencies
pip install -e ".[dev]"
```

### Configure

```bash
cp config.toml config-local.toml
```

Edit `config-local.toml` — at minimum set your kubeconfig path and namespace:

```toml
[kubernetes]
kubeconfig = "/home/youruser/.kube/config"
namespace  = "litterbox-dev"

[celery]
broker_url     = "redis://localhost:6379/2"
result_backend = "redis://localhost:6379/2"
```

Set the config path via env var:
```bash
export ORCHESTRATOR_CONFIG=./config-local.toml
```

### Run Services

Each process runs in a **separate terminal** with the venv activated.

**API server:**
```bash
uvicorn orchestrator.main:app --reload --port 8080
# Interactive docs: http://localhost:8080/docs
```

**Celery worker** (pool reconcile + webhook delivery):
```bash
celery -A orchestrator.celery_app:celery_app worker \
  -l info \
  -Q pool_reconcile,webhook_delivery \
  -n worker@%h
```

**TTL reaper:**
```bash
python -m orchestrator.worker_runner ttl
```

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
│   └── models.py          # All Pydantic v2 models (Template, Sandbox, Pool, Webhook…)
├── infra/
│   ├── kubernetes.py      # KubernetesGateway — every K8s API call lives here
│   ├── repositories.py    # ConfigMap-backed repos (TemplateRepo, PoolRepo, WebhookRepo)
│   └── ttl_queue.py       # Redis sorted-set TTL queue operations
├── services/
│   ├── sandboxes.py       # Sandbox lifecycle business logic
│   ├── pools.py           # Pool management + reconcile loop
│   ├── templates.py       # Template CRUD
│   ├── webhooks.py        # Webhook delivery
│   ├── workspace.py       # File ops + exec inside sandboxes
│   ├── exposes.py         # Service/Ingress expose management
│   ├── metrics.py         # Prometheus + in-memory snapshot
│   └── ttl.py             # TTL service layer
├── container.py           # Dependency injection — wires all services together
├── main.py                # FastAPI app, all route definitions, DI bootstrap
├── tasks.py               # Celery task definitions
├── celery_app.py          # Celery app instance
├── config.py              # Settings model (pydantic-settings, TOML + env vars)
├── utils.py               # Shared utilities (short_id, label sanitization…)
└── worker_runner.py       # Entry point for non-Celery workers (TTL scanner)
```

---

## Frontend (`frontend/`)

### Setup

```bash
cd frontend
npm install          # or: pnpm install
```

### Configure

```bash
cp .env.example .env
```

```dotenv
VITE_API_BASE_URL=http://localhost:8080
```

### Run

```bash
npm run dev
# http://localhost:5173

# Type-check only (no emit)
npm run check

# Production build → dist/
npm run build

# Preview production build locally
npm run preview
```


