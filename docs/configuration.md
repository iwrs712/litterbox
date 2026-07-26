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
- [workspace](#workspace)
- [envd](#envd)
- [e2b](#e2b)
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
| `api` | `uvicorn` | REST API、E2B 控制面和 envd 代理，需要 K8s + Redis 访问权限 |
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
| `runtime_class` | string | `"kata-clh"` | Pod 的 [runtimeClassName](https://kubernetes.io/docs/concepts/containers/runtime-class/)。仅在集群中确实存在该 RuntimeClass 时生效；不存在时回退到集群默认 runtime |
| `storage_class` | string | *空* | workspace 未单独配置 StorageClass 时的回退值 |
| `image_pull_secret` | string | *空* | 拉取私有镜像的 `kubernetes.io/dockerconfigjson` Secret 名称。公开镜像留空 |

**环境变量：**

```
ORCHESTRATOR__KUBERNETES__KUBECONFIG=/path/to/kubeconfig
ORCHESTRATOR__KUBERNETES__NAMESPACE=default
ORCHESTRATOR__KUBERNETES__RUNTIME_CLASS=kata-clh
ORCHESTRATOR__KUBERNETES__STORAGE_CLASS=litterbox-workspace-lvm
ORCHESTRATOR__KUBERNETES__IMAGE_PULL_SECRET=harbor-pull-secret
```

```toml
[kubernetes]
kubeconfig        = ""
namespace         = "default"
runtime_class     = "kata-clh"
storage_class     = ""
image_pull_secret = ""
```

> **in-cluster vs 本地开发**：部署在 Kubernetes 内时 `kubeconfig` 留空（生产标准配置）。本地开发时指向你的 kubeconfig 文件。

---

## [sandbox]

沙箱全局配置。

| Key | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `max_sandboxes` | integer | `1000` | 沙箱数量上限配置。当前用于限制 envd Pod IP 缓存大小，未在创建路径强制拒绝 |
| `base_domain` | string | `"example.com"` | HTTP 暴露的通配符域名。每个沙箱的暴露端口路由为 `<sandbox-id>.<base_domain>`。需要配置 `*.<base_domain>` 的 DNS 记录指向 Ingress Controller |

**环境变量：**

```
ORCHESTRATOR__SANDBOX__MAX_SANDBOXES=1000
ORCHESTRATOR__SANDBOX__BASE_DOMAIN=sandbox.example.com
```

```toml
[sandbox]
max_sandboxes = 1000
base_domain   = "example.com"
```

---

## [workspace]

每个 Sandbox 的 `/workspace` 持久卷配置。Template 或创建请求中的 `workspace` 字段可以按沙箱覆盖这些值。

| Key | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `enabled` | boolean | `true` | 是否创建并挂载 workspace PVC |
| `mount_path` | string | `"/workspace"` | 容器内挂载路径，必须是绝对路径 |
| `default_size` | string | `"1Gi"` | 未指定大小时的 PVC 容量 |
| `storage_class` | string | `"litterbox-workspace-lvm"` | PVC 使用的 StorageClass；为空时回退到 `kubernetes.storage_class` |

**环境变量：**

```
ORCHESTRATOR__WORKSPACE__ENABLED=true
ORCHESTRATOR__WORKSPACE__MOUNT_PATH=/workspace
ORCHESTRATOR__WORKSPACE__DEFAULT_SIZE=1Gi
ORCHESTRATOR__WORKSPACE__STORAGE_CLASS=litterbox-workspace-lvm
```

```toml
[workspace]
enabled       = true
mount_path    = "/workspace"
default_size  = "1Gi"
storage_class = "litterbox-workspace-lvm"
```

> PVC 在暂停/恢复后保留；只有永久删除 Sandbox 时才会删除。StorageClass 需要按部署环境提前安装。

---

## [envd]

envd 数据面配置。启用后，每个 Sandbox 主容器会通过 `postStart` 启动 envd，orchestrator 通过它提供命令执行、文件读写和 PTY。

| Key | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `enabled` | boolean | `false` | 是否向 Sandbox 注入并启动 envd |
| `version` | string | `"0.1.0"` | envd 版本，同时作为节点选择标签 `litterbox.io/envd-version` |
| `host_binary_path` | string | `"/opt/litterbox/bin/envd"` | 节点上的二进制路径，由 installer DaemonSet 写入 |
| `container_binary_path` | string | `"/opt/litterbox/bin/envd"` | 容器内的只读挂载路径 |
| `port` | integer | `49983` | envd 监听端口 |
| `connect_timeout_seconds` | float | `3.0` | 代理连接 envd 的超时 |
| `pod_ip_cache_ttl_seconds` | float | `5.0` | Pod IP 缓存时间；`0` 表示不缓存 |

**环境变量：**

```
ORCHESTRATOR__ENVD__ENABLED=true
ORCHESTRATOR__ENVD__VERSION=0.1.0
ORCHESTRATOR__ENVD__HOST_BINARY_PATH=/opt/litterbox/bin/envd
ORCHESTRATOR__ENVD__CONTAINER_BINARY_PATH=/opt/litterbox/bin/envd
ORCHESTRATOR__ENVD__PORT=49983
```

```toml
[envd]
enabled                 = true
version                 = "0.1.0"
host_binary_path        = "/opt/litterbox/bin/envd"
container_binary_path   = "/opt/litterbox/bin/envd"
port                    = 49983
connect_timeout_seconds = 3.0
pod_ip_cache_ttl_seconds = 5.0
```

> 启用前必须先在 Kata 节点上安装 envd。节点缺少对应版本标签时，新 Sandbox 会保持 Pending。

---

## [e2b]

E2B 兼容控制面配置。启用后，官方 E2B SDK 可以访问 `/e2b/sandboxes` 和 `49983-{sandbox_id}.{domain}` 数据面。

| Key | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `enabled` | boolean | `true` | 是否启用 `/e2b` 控制面和通配域名路由 |
| `api_key` | string | `""` | E2B `X-API-Key`；为空时接受 `auth.bearer_token` |
| `domain` | string | `"sandbox.example.com"` | 数据面通配域名。需要 `*.{domain}` 的 DNS 和 TLS 指向 orchestrator |
| `envd_version` | string | `"0.1.0"` | 返回给 SDK 的 envd 版本 |

**环境变量：**

```
ORCHESTRATOR__E2B__ENABLED=true
ORCHESTRATOR__E2B__API_KEY=replace-with-e2b-key
ORCHESTRATOR__E2B__DOMAIN=sandbox.example.com
ORCHESTRATOR__E2B__ENVD_VERSION=0.1.0
```

```toml
[e2b]
enabled      = true
api_key      = ""
domain       = "sandbox.example.com"
envd_version = "0.1.0"
```

> 完整 SDK 用法与支持范围见 [orchestrator/docs/API.md](../orchestrator/docs/API.md)。

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
| `bearer_token` | string | `""` | 私有 API 的 Bearer Token。为空表示不启用鉴权；非空时要求访问 `/api/v1/*` 的客户端携带 `Authorization: Bearer <token>` |

**环境变量：**

```
ORCHESTRATOR__AUTH__BEARER_TOKEN=replace-with-strong-token
```

```toml
[auth]
bearer_token = ""
```

> E2B 路由使用 `X-API-Key`（或 `X-Access-Token` / Bearer）。`e2b.api_key` 为空时回退使用这里的 `bearer_token`。

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
runtime_class     = "kata-clh"                  # VM 级隔离（不存在时回退）
storage_class     = "ceph-rbd"
image_pull_secret = "harbor-pull-secret"

[sandbox]
max_sandboxes = 5000
base_domain   = "sandbox.example.com"

[workspace]
enabled       = true
mount_path    = "/workspace"
default_size  = "1Gi"
storage_class = "litterbox-workspace-lvm"

[envd]
enabled = true
version = "0.1.0"

[e2b]
enabled      = true
api_key      = ""
domain       = "sandbox.example.com"
envd_version = "0.1.0"

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
| `ORCHESTRATOR__KUBERNETES__RUNTIME_CLASS` | `kubernetes.runtime_class` | `kata-clh` |
| `ORCHESTRATOR__KUBERNETES__STORAGE_CLASS` | `kubernetes.storage_class` | *空* |
| `ORCHESTRATOR__KUBERNETES__IMAGE_PULL_SECRET` | `kubernetes.image_pull_secret` | *空* |
| `ORCHESTRATOR__WORKSPACE__ENABLED` | `workspace.enabled` | `true` |
| `ORCHESTRATOR__WORKSPACE__MOUNT_PATH` | `workspace.mount_path` | `/workspace` |
| `ORCHESTRATOR__WORKSPACE__DEFAULT_SIZE` | `workspace.default_size` | `1Gi` |
| `ORCHESTRATOR__WORKSPACE__STORAGE_CLASS` | `workspace.storage_class` | `litterbox-workspace-lvm` |
| `ORCHESTRATOR__ENVD__ENABLED` | `envd.enabled` | `false` |
| `ORCHESTRATOR__ENVD__VERSION` | `envd.version` | `0.1.0` |
| `ORCHESTRATOR__ENVD__HOST_BINARY_PATH` | `envd.host_binary_path` | `/opt/litterbox/bin/envd` |
| `ORCHESTRATOR__ENVD__CONTAINER_BINARY_PATH` | `envd.container_binary_path` | `/opt/litterbox/bin/envd` |
| `ORCHESTRATOR__ENVD__PORT` | `envd.port` | `49983` |
| `ORCHESTRATOR__ENVD__CONNECT_TIMEOUT_SECONDS` | `envd.connect_timeout_seconds` | `3.0` |
| `ORCHESTRATOR__ENVD__POD_IP_CACHE_TTL_SECONDS` | `envd.pod_ip_cache_ttl_seconds` | `5.0` |
| `ORCHESTRATOR__E2B__ENABLED` | `e2b.enabled` | `true` |
| `ORCHESTRATOR__E2B__API_KEY` | `e2b.api_key` | `""` |
| `ORCHESTRATOR__E2B__DOMAIN` | `e2b.domain` | `sandbox.example.com` |
| `ORCHESTRATOR__E2B__ENVD_VERSION` | `e2b.envd_version` | `0.1.0` |
| `ORCHESTRATOR__SANDBOX__MAX_SANDBOXES` | `sandbox.max_sandboxes` | `1000` |
| `ORCHESTRATOR__SANDBOX__BASE_DOMAIN` | `sandbox.base_domain` | `example.com` |
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
