# Configuration Reference

后端通过两层配置加载，**环境变量始终优先于 `config.toml`**。

| 优先级 | 来源 | 说明 |
|---|---|---|
| **1（最高）** | 环境变量 | 前缀 `ORCHESTRATOR__`，双下划线分隔层级 |
| **2** | `config.toml` | 默认路径 `./config.toml` |

---

## 目录

- [进程角色](#进程角色)
- [server](#server)
- [kubernetes](#kubernetes)
- [sandbox](#sandbox)
- [ttl](#ttl)
- [webhook](#webhook)
- [celery](#celery)
- [auth](#auth)
- [完整示例](#完整示例)
- [快速参照表](#快速参照表)

---

## 进程角色

通过 `entrypoint.sh` 的第一个参数或 `ORCHESTRATOR_ROLE` 环境变量选择角色。同一镜像，不同启动命令。

```bash
# Docker / docker-compose
command: ["api"]      # 或 "worker"
# 或通过环境变量
ORCHESTRATOR_ROLE=api
```

| 角色 | 进程 | 说明 |
|---|---|---|
| `api` | `uvicorn` | REST API + WebSocket，需要 K8s + Redis 访问权限 |
| `worker` | `celery` + TTL 子进程 | 消费 `pool_reconcile` 和 `webhook_delivery` 队列，同时在后台运行 TTL 清理子进程 |

> **注意**：`worker` 角色会在后台启动 TTL 子进程，再前台 exec celery。不需要单独部署 TTL 进程。

---

## [server]

HTTP API 监听配置。

| Key | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `host` | string | `"0.0.0.0"` | 监听地址。设为 `"127.0.0.1"` 可限制仅本地访问 |
| `port` | integer | `8080` | 监听端口 |

**环境变量：**

```
ORCHESTRATOR__SERVER__HOST=0.0.0.0
ORCHESTRATOR__SERVER__PORT=8080
```

```toml
[server]
host = "0.0.0.0"
port = 8080
```

---

## [kubernetes]

Kubernetes API 连接配置。

| Key | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `kubeconfig` | string | *空* | kubeconfig 文件路径。**为空时使用 in-cluster 模式**（读取 ServiceAccount token）。本地开发设为 `~/.kube/config` |
| `namespace` | string | `"default"` | 沙箱资源（Deployment、Service、Ingress）创建的 namespace |
| `runtime_class` | string | *空* | Pod 的 [runtimeClassName](https://kubernetes.io/docs/concepts/containers/runtime-class/)。设为 `"kata-cloud-hypervisor"` 可获得 VM 级隔离。为空使用集群默认 runtime |
| `storage_class` | string | *空* | PVC 使用的 StorageClass |
| `image_pull_secret` | string | *空* | 拉取私有镜像的 `kubernetes.io/dockerconfigjson` Secret 名称。公开镜像留空 |

**环境变量：**

```
ORCHESTRATOR__KUBERNETES__KUBECONFIG=/path/to/kubeconfig
ORCHESTRATOR__KUBERNETES__NAMESPACE=default
ORCHESTRATOR__KUBERNETES__RUNTIME_CLASS=kata-cloud-hypervisor
ORCHESTRATOR__KUBERNETES__STORAGE_CLASS=local-path
ORCHESTRATOR__KUBERNETES__IMAGE_PULL_SECRET=harbor-pull-secret
```

```toml
[kubernetes]
kubeconfig        = ""
namespace         = "default"
runtime_class     = ""
storage_class     = ""
image_pull_secret = ""
```

> **in-cluster vs 本地开发**：部署在 Kubernetes 内时 `kubeconfig` 留空（生产标准配置）。本地开发时指向你的 kubeconfig 文件。

---

## [sandbox]

沙箱全局配置。

| Key | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `max_sandboxes` | integer | `1000` | 最大同时存在的沙箱数量，超出返回 `429` |
| `base_domain` | string | `"runlet.cn"` | HTTP 暴露的通配符域名。每个沙箱的暴露端口路由为 `<sandbox-id>.<base_domain>`。需要配置 `*.<base_domain>` 的 DNS 记录指向 Ingress Controller |

**环境变量：**

```
ORCHESTRATOR__SANDBOX__MAX_SANDBOXES=1000
ORCHESTRATOR__SANDBOX__BASE_DOMAIN=sandbox.example.com
```

```toml
[sandbox]
max_sandboxes = 1000
base_domain   = "runlet.cn"
```

---

## [ttl]

TTL 生命周期管理配置。

| Key | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `default_ttl_seconds` | integer | `1800` | 沙箱未指定 TTL 时的默认存活时间（30 分钟） |
| `min_ttl_seconds` | integer | `60` | 允许设置的最小 TTL（1 分钟） |
| `max_ttl_seconds` | integer | `86400` | 允许设置的最大 TTL（24 小时） |
| `queue_key` | string | `"orchestrator:ttl"` | Redis 有序集合的 key 名，存储 `(sandbox_id, expiry_timestamp)` 对。API 和 Worker 必须使用相同的值 |
| `worker_poll_interval_seconds` | float | `1.0` | TTL worker 扫描过期沙箱的间隔。更低 = 更及时但 Redis 负载更高 |

**环境变量：**

```
ORCHESTRATOR__TTL__DEFAULT_TTL_SECONDS=1800
ORCHESTRATOR__TTL__MIN_TTL_SECONDS=60
ORCHESTRATOR__TTL__MAX_TTL_SECONDS=86400
ORCHESTRATOR__TTL__QUEUE_KEY=orchestrator:ttl
ORCHESTRATOR__TTL__WORKER_POLL_INTERVAL_SECONDS=1.0
```

```toml
[ttl]
default_ttl_seconds          = 1800
min_ttl_seconds              = 60
max_ttl_seconds              = 86400
queue_key                    = "orchestrator:ttl"
worker_poll_interval_seconds = 1.0
```

---

## [webhook]

Webhook 事件投递配置。

| Key | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `max_attempts` | integer | `5` | 每个事件的最大投递次数（首次 + 重试）。使用 Celery `self.retry` 机制，重试期间不占用 worker 线程 |
| `interval_ms` | integer | `200` | 重试间隔（毫秒） |
| `timeout_ms` | integer | `1000` | 单次 HTTP 请求超时（毫秒） |

**环境变量：**

```
ORCHESTRATOR__WEBHOOK__MAX_ATTEMPTS=5
ORCHESTRATOR__WEBHOOK__INTERVAL_MS=200
ORCHESTRATOR__WEBHOOK__TIMEOUT_MS=1000
```

```toml
[webhook]
max_attempts = 5
interval_ms  = 200
timeout_ms   = 1000
```

---

## [celery]

Celery 任务队列配置。

| Key | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `broker_url` | string | `"redis://127.0.0.1:6379/2"` | Celery broker 的 Redis 地址。默认使用 DB 2 隔离任务消息 |
| `result_backend` | string | `"redis://127.0.0.1:6379/2"` | Celery result backend 地址。API 和 Worker 都需要访问 |
| `webhook_queue` | string | `"webhook_delivery"` | Webhook 投递任务使用的队列名 |

**环境变量：**

```
ORCHESTRATOR__CELERY__BROKER_URL=redis://redis:6379/2
ORCHESTRATOR__CELERY__RESULT_BACKEND=redis://redis:6379/2
ORCHESTRATOR__CELERY__WEBHOOK_QUEUE=webhook_delivery
```

```toml
[celery]
broker_url      = "redis://127.0.0.1:6379/2"
result_backend  = "redis://127.0.0.1:6379/2"
webhook_queue   = "webhook_delivery"
```

> **建议的 Redis DB 分配：**
>
> | DB | 用途 |
> |---|---|
> | 0 | 通用缓存 |
> | 1 | TTL 有序集合（`orchestrator:ttl`） |
> | 2 | Celery broker + result backend |

---

## [auth]

API 鉴权配置（可选）。

| Key | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `bearer_token` | string | `""` | API Bearer Token。为空表示不启用鉴权；非空时要求客户端携带 Bearer Token 访问 `/api/v1/*`，WebSocket 端点也会校验 |

**环境变量：**

```
ORCHESTRATOR__AUTH__BEARER_TOKEN=replace-with-strong-token
```

```toml
[auth]
bearer_token = ""
```

> WebSocket 浏览器客户端通常无法设置自定义 `Authorization` header，可通过查询参数传递：`?token=<token>`。

---

## 完整示例

### 本地开发（docker-compose）

```toml
[server]
host = "0.0.0.0"
port = 8080

[kubernetes]
kubeconfig        = "k3s.yaml"          # 本地 kubeconfig
namespace         = "default"
runtime_class     = ""
storage_class     = "local-path"
image_pull_secret = ""

[sandbox]
max_sandboxes = 100
base_domain   = "localhost"

[ttl]
default_ttl_seconds          = 300      # 开发环境 5 分钟，加快清理
min_ttl_seconds              = 30
max_ttl_seconds              = 3600
queue_key                    = "orchestrator:ttl"
worker_poll_interval_seconds = 1.0

[webhook]
max_attempts = 3
interval_ms  = 500
timeout_ms   = 3000

[celery]
broker_url      = "redis://redis:6379/2"
result_backend  = "redis://redis:6379/2"
webhook_queue   = "webhook_delivery"

[auth]
bearer_token = ""
```

### 生产环境（Kubernetes in-cluster）

```toml
[server]
host = "0.0.0.0"
port = 8080

[kubernetes]
kubeconfig        = ""                          # in-cluster 认证
namespace         = "litterbox-sandboxes"
runtime_class     = "kata-cloud-hypervisor"     # VM 级隔离
storage_class     = "ceph-rbd"
image_pull_secret = "harbor-pull-secret"

[sandbox]
max_sandboxes = 5000
base_domain   = "sandbox.example.com"

[ttl]
default_ttl_seconds          = 1800
min_ttl_seconds              = 60
max_ttl_seconds              = 86400
queue_key                    = "orchestrator:ttl"
worker_poll_interval_seconds = 1.0

[webhook]
max_attempts = 5
interval_ms  = 200
timeout_ms   = 1000

[celery]
# 敏感值建议通过 Kubernetes Secret 的环境变量注入：
# ORCHESTRATOR__CELERY__BROKER_URL
# ORCHESTRATOR__CELERY__RESULT_BACKEND
broker_url      = "redis://:password@redis.litterbox.svc.cluster.local:6379/2"
result_backend  = "redis://:password@redis.litterbox.svc.cluster.local:6379/2"
webhook_queue   = "webhook_delivery"

[auth]
bearer_token = "replace-with-strong-token"
```

---

## 快速参照表

| 环境变量 | 映射到 | 默认值 |
|---|---|---|
| `ORCHESTRATOR_ROLE` | 进程角色 | `api` |
| `ORCHESTRATOR__SERVER__HOST` | `server.host` | `0.0.0.0` |
| `ORCHESTRATOR__SERVER__PORT` | `server.port` | `8080` |
| `ORCHESTRATOR__KUBERNETES__KUBECONFIG` | `kubernetes.kubeconfig` | *空* |
| `ORCHESTRATOR__KUBERNETES__NAMESPACE` | `kubernetes.namespace` | `default` |
| `ORCHESTRATOR__KUBERNETES__RUNTIME_CLASS` | `kubernetes.runtime_class` | *空* |
| `ORCHESTRATOR__KUBERNETES__STORAGE_CLASS` | `kubernetes.storage_class` | *空* |
| `ORCHESTRATOR__KUBERNETES__IMAGE_PULL_SECRET` | `kubernetes.image_pull_secret` | *空* |
| `ORCHESTRATOR__SANDBOX__MAX_SANDBOXES` | `sandbox.max_sandboxes` | `1000` |
| `ORCHESTRATOR__SANDBOX__BASE_DOMAIN` | `sandbox.base_domain` | `runlet.cn` |
| `ORCHESTRATOR__TTL__DEFAULT_TTL_SECONDS` | `ttl.default_ttl_seconds` | `1800` |
| `ORCHESTRATOR__TTL__MIN_TTL_SECONDS` | `ttl.min_ttl_seconds` | `60` |
| `ORCHESTRATOR__TTL__MAX_TTL_SECONDS` | `ttl.max_ttl_seconds` | `86400` |
| `ORCHESTRATOR__TTL__QUEUE_KEY` | `ttl.queue_key` | `orchestrator:ttl` |
| `ORCHESTRATOR__TTL__WORKER_POLL_INTERVAL_SECONDS` | `ttl.worker_poll_interval_seconds` | `1.0` |
| `ORCHESTRATOR__WEBHOOK__MAX_ATTEMPTS` | `webhook.max_attempts` | `5` |
| `ORCHESTRATOR__WEBHOOK__INTERVAL_MS` | `webhook.interval_ms` | `200` |
| `ORCHESTRATOR__WEBHOOK__TIMEOUT_MS` | `webhook.timeout_ms` | `1000` |
| `ORCHESTRATOR__CELERY__BROKER_URL` | `celery.broker_url` | `redis://127.0.0.1:6379/2` |
| `ORCHESTRATOR__CELERY__RESULT_BACKEND` | `celery.result_backend` | `redis://127.0.0.1:6379/2` |
| `ORCHESTRATOR__CELERY__WEBHOOK_QUEUE` | `celery.webhook_queue` | `webhook_delivery` |
| `ORCHESTRATOR__AUTH__BEARER_TOKEN` | `auth.bearer_token` | `""` |
