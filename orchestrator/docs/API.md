# Litterbox E2B API

Litterbox 实现了 E2B 控制面和 envd 数据面的兼容子集。推荐使用官方 E2B SDK 访问 sandbox：控制面负责创建、查询、暂停、恢复、续期和永久删除，envd 数据面负责命令执行、文件操作和 PTY。

本文中的地址均为占位示例：

```text
控制面  https://orchestrator.example.com/e2b
数据面  https://49983-{sandbox_id}.sandbox.example.com
```

## 1. 配置

| 配置项 | 说明 |
| --- | --- |
| `ORCHESTRATOR__E2B__ENABLED` | 启用 `/e2b` 控制面和通配域名路由 |
| `ORCHESTRATOR__E2B__API_KEY` | 客户端通过 `X-API-Key` 携带；为空时接受 orchestrator 的 Bearer Token |
| `ORCHESTRATOR__E2B__DOMAIN` | 数据面通配域名，例如 `sandbox.example.com` |
| `ORCHESTRATOR__ENVD__ENABLED` | 在 sandbox 中注入并启动 envd |

通配域名的 DNS 和 TLS 需要指向 orchestrator。请求格式：

```text
49983-{sandbox_id}.{ORCHESTRATOR__E2B__DOMAIN}
```

`49983` 是 envd 监听端口。官方 SDK 会根据创建响应自动构造数据面地址并处理 Connect RPC 协议。

## 2. Python SDK

```bash
pip install e2b
```

### 2.1 同步调用

```python
from e2b import Sandbox

config = {
    "api_url": "https://orchestrator.example.com/e2b",
    "domain": "sandbox.example.com",
    "api_key": "<E2B_API_KEY>",
    "request_timeout": 60,
}

sandbox = Sandbox.create(
    template="ubuntu",
    timeout=300,
    metadata={"job_id": "1001"},
    envs={"JOB_ID": "1001"},
    **config,
)

print("sandbox_id:", sandbox.sandbox_id)

result = sandbox.commands.run("printf 'hello from sandbox'")
print(result.stdout)

sandbox.files.write("/workspace/hello.txt", "persistent workspace data")
print(sandbox.files.read("/workspace/hello.txt"))

# 缩容到 0，保留 workspace PVC。
sandbox.pause(keep_memory=False)

# 重新连接；connect 会恢复已暂停的 sandbox。
connected = Sandbox.connect(sandbox.sandbox_id, **config)
print(connected.files.read("/workspace/hello.txt"))
connected.set_timeout(600)

# 永久删除 sandbox、PVC、Service 和 Ingress。
connected.kill()
```

### 2.2 异步调用

```python
from e2b import AsyncSandbox

config = {
    "api_url": "https://orchestrator.example.com/e2b",
    "domain": "sandbox.example.com",
    "api_key": "<E2B_API_KEY>",
    "request_timeout": 60,
}

sandbox = await AsyncSandbox.create(template="ubuntu", timeout=300, **config)

try:
    result = await sandbox.commands.run("python -c 'print(1 + 1)'")
    print(result.stdout)
finally:
    await sandbox.kill()
```

### 2.3 不要用 context manager 自动结束

官方 SDK 的 context manager 退出时会调用 `kill()`；在 Litterbox 中 `kill()` 是永久删除，会同时删除 workspace PVC。需要保留 workspace 时，显式调用 `pause(keep_memory=False)`。

## 3. Template 与 workspace

E2B SDK 的 `Sandbox.create()` 只选择已有 Template，不负责创建 Template。SDK 另有 `Template.build()` / `from_dockerfile()` / `from_image()`，用于在 E2B 云端构建模板；Litterbox 未实现这组构建接口，模板通过私有管理 API 创建。

```http
POST https://orchestrator.example.com/api/v1/templates
Authorization: Bearer <ORCHESTRATOR_BEARER_TOKEN>
Content-Type: application/json
```

```json
{
  "id": "python-worker",
  "name": "Python Worker",
  "image": "python:3.12-slim",
  "command": "sleep infinity",
  "cpu_millicores": 1000,
  "memory_mb": 1024,
  "workspace": {
    "enabled": true,
    "mount_path": "/workspace",
    "size": "10Gi",
    "storage_class": "litterbox-workspace-lvm"
  },
  "ttl_seconds": 3600,
  "metadata": {"owner": "platform"}
}
```

workspace 字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `enabled` | boolean | 是否创建并挂载独立 workspace PVC |
| `mount_path` | string | 容器内挂载路径，必须是绝对路径 |
| `size` | string | PVC 大小，例如 `1Gi`、`10Gi` |
| `storage_class` | string/null | 默认使用全局 workspace 配置 |

workspace 生命周期：

- 每个 sandbox 拥有独立 PVC。
- `pause(keep_memory=False)` 或私有 API `suspend` 将 `spec.state` 置为 `Paused`，控制器删除 Pod 并保留 PVC。
- `connect()` 或私有 API `resume` 将 `spec.state` 置为 `Running`，控制器重新创建 Pod 并挂载原 PVC。
- `kill()` 或私有 API `DELETE /api/v1/sandboxes/{id}` 删除 Sandbox CR，Pod 和 PVC 由 Kubernetes GC 回收。
- Template 的 workspace 配置影响后续新建 sandbox，不会自动修改已有 PVC。

## 4. E2B 控制面接口

E2B 控制面不返回 Litterbox 的 `{success, data}` 包装，而是返回 E2B 风格的原生对象。

### 4.1 创建 sandbox

```http
POST https://orchestrator.example.com/e2b/sandboxes
X-API-Key: <E2B_API_KEY>
Content-Type: application/json
```

```json
{
  "templateID": "ubuntu",
  "timeout": 300,
  "metadata": {"job_id": "1001"},
  "envVars": {"JOB_ID": "1001"},
  "secure": true,
  "allow_internet_access": true
}
```

成功响应：

```json
{
  "templateID": "ubuntu",
  "sandboxID": "abc12345",
  "clientID": "litterbox",
  "domain": "sandbox.example.com",
  "envdVersion": "0.1.0",
  "envdAccessToken": "<ENVD_ACCESS_TOKEN>",
  "trafficAccessToken": null
}
```

创建响应中的 `envdAccessToken` 由 SDK 自动用于数据面，上游不需要自行拼接认证头。

### 4.2 查询 sandbox

```http
GET https://orchestrator.example.com/e2b/sandboxes/{sandbox_id}
X-API-Key: <E2B_API_KEY>
```

`state` 取值：

| state | 含义 |
| --- | --- |
| `running` | Sandbox CR 有运行中的 Pod |
| `paused` | Sandbox CR 已暂停，Pod 已删除，workspace 保留 |
| `dead` | sandbox 已退出或不可用 |

### 4.3 连接并恢复

```http
POST https://orchestrator.example.com/e2b/sandboxes/{sandbox_id}/connect
X-API-Key: <E2B_API_KEY>
Content-Type: application/json
```

```json
{"timeout": 300}
```

已暂停的 sandbox 会被恢复；被锁定的 sandbox 返回 `409`。

### 4.4 暂停

```http
POST https://orchestrator.example.com/e2b/sandboxes/{sandbox_id}/pause
X-API-Key: <E2B_API_KEY>
Content-Type: application/json
```

```json
{"memory": false}
```

只支持文件系统级暂停。`keep_memory=True` 返回 `409`，因为当前没有实现内存快照。

### 4.5 修改 timeout

```http
POST https://orchestrator.example.com/e2b/sandboxes/{sandbox_id}/timeout
X-API-Key: <E2B_API_KEY>
Content-Type: application/json
```

```json
{"timeout": 600}
```

`0` 表示不超时。部分 SDK 版本在 `Sandbox.create(timeout=0)` 时会使用 SDK 默认值；需要永久保留时，建议创建后调用 `sandbox.set_timeout(0)`。

### 4.6 永久删除

```http
DELETE https://orchestrator.example.com/e2b/sandboxes/{sandbox_id}
X-API-Key: <E2B_API_KEY>
```

不可恢复，会删除 Sandbox CR；Pod、workspace PVC 和 expose 对应的 Service/Ingress 由控制器和 GC 清理。成功返回 `204 No Content`。

## 5. envd 数据面

### 5.1 SDK 调用

```python
result = sandbox.commands.run("pwd && ls -la /workspace")
print(result.stdout)

sandbox.files.write("/workspace/result.json", '{"ok": true}')
content = sandbox.files.read("/workspace/result.json")
print(content)
```

SDK 会处理 envd 的 Connect RPC framing。不要把 `Process/Start` 当成普通 JSON REST 接口直接发送裸 JSON，否则会得到协议错误或 `415`。

### 5.2 数据面地址与鉴权

SDK 使用创建响应中的 `domain`、`envdAccessToken` 和端口 `49983`，通过下面的 Host 路由：

```text
Host: 49983-{sandbox_id}.sandbox.example.com
```

使用普通 HTTP 客户端检查 envd 时，可以携带：

```http
X-Access-Token: <ENVD_ACCESS_TOKEN>
```

```bash
curl -i \
  "https://49983-abc12345.sandbox.example.com/health" \
  -H "X-Access-Token: $E2B_API_KEY"
```

生产环境优先使用官方 SDK，避免自行实现 Connect RPC、流式响应和 hostname 路由。

### 5.3 路径代理

编排器保留内部路径代理，使用私有 API 的 Bearer Token：

```text
https://orchestrator.example.com/api/v1/sandboxes/{sandbox_id}/envd/{envd_path}
```

该路径主要用于 Dashboard 和诊断，官方 E2B SDK 不应把它作为主数据面地址。

## 6. 沙箱锁

沙箱锁用于标记当前 sandbox 不应被恢复。被锁定后：

- 可以被 TTL 自动暂停。
- 可以查询、查看日志。
- 恢复操作会被拒绝。
- 删除仍然允许。

```http
POST https://orchestrator.example.com/api/v1/sandboxes/{sandbox_id}/lock
Authorization: Bearer <ORCHESTRATOR_BEARER_TOKEN>
```

```http
POST https://orchestrator.example.com/api/v1/sandboxes/{sandbox_id}/unlock
Authorization: Bearer <ORCHESTRATOR_BEARER_TOKEN>
```

SDK 没有标准的 lock/unlock 方法，只能通过私有管理 API 使用。解锁后 `Sandbox.connect()` 才可以恢复。

## 7. 支持范围

### 已支持

- `Sandbox.create`
- `Sandbox.connect`
- `Sandbox.pause(keep_memory=False)`
- `Sandbox.set_timeout`
- `Sandbox.kill`
- sandbox 查询
- envd 命令执行、文件读写、PTY/流式 Connect RPC
- sandbox hostname 数据面路由
- workspace PVC 与暂停/恢复后的持久化
- Template workspace 默认配置
- sandbox 锁

### 暂不支持

| E2B 能力 | 当前状态 |
| --- | --- |
| `pause(keep_memory=True)` 内存快照 | 返回 `409` |
| snapshots | 不支持 |
| fork | 不支持 |
| E2B volumes API | 不支持；workspace 通过 Template 配置 |
| Template build（`Template.build` / Dockerfile 构建） | 不支持；使用 `/api/v1/templates` 创建镜像模板 |
| network allow/deny 策略 | 不支持；`allow_internet_access=false` 返回 `400` |
| traffic proxy token | 返回 `null` |

## 8. 错误与排查

### 控制面

| HTTP 状态 | 含义 |
| --- | --- |
| `400` | 参数非法，或请求了不支持的能力 |
| `401` | `X-API-Key` 缺失或错误 |
| `404` | sandbox/template 不存在，或 E2B 控制面未启用 |
| `409` | 当前状态不允许操作，例如锁定 sandbox 恢复、请求内存快照 |
| `500` | 编排器或 Kubernetes 操作失败 |

### 数据面

| 错误 | 常见原因 |
| --- | --- |
| TLS `NotValidForName` | 通配域名或证书未配置 |
| `401 Unauthorized` | SDK 未拿到 `envdAccessToken`，或请求缺少 `X-Access-Token` |
| `409 sandbox is not running` | sandbox 已暂停，需要先 `Sandbox.connect()` |
| `502 envd upstream unavailable` | Pod 未 ready、envd 未启动或 Pod 地址不可用 |
| `503 sandbox pod address unavailable` | sandbox 没有可用的 Running Pod |
| `415` / Connect 协议错误 | 把 envd 的 Connect RPC 当成裸 JSON REST 调用 |

### workspace PVC Pending

```bash
kubectl get pod -A -l component=sandbox -o wide
kubectl get pvc -A
kubectl describe pod -n <namespace> <pod-name>
kubectl get lvmnode -n openebs
```

确认 StorageClass 有可用容量、PVC 已 `Bound`，以及 Pod 没有因为存储不足或 `WaitForFirstConsumer` 而 Pending。

## 9. 健康检查与 OpenAPI

```bash
curl -sS https://orchestrator.example.com/health
```

| 方法 | 地址 | 用途 |
| --- | --- | --- |
| `GET` | `https://orchestrator.example.com/` | 服务根路径 |
| `GET` | `https://orchestrator.example.com/metrics` | Prometheus 指标 |
| `GET` | `https://orchestrator.example.com/api/v1/metrics/snapshot` | JSON 指标快照 |
| `GET` | `https://orchestrator.example.com/openapi.json` | OpenAPI |
| `GET` | `https://orchestrator.example.com/docs` | Swagger UI |

当前 OpenAPI 主要描述私有 `/api/v1` 路由；E2B 路由以上述 SDK 示例为准。
