# Litterbox E2B API

本文档面向接入 Litterbox sandbox 服务的上游业务。推荐使用官方 E2B Python SDK 访问 sandbox；Litterbox 的 E2B 兼容控制面负责创建、查询、暂停、恢复、续期和永久删除 sandbox，envd 数据面负责执行命令、文件操作和 PTY。

文档对应当前线上部署，更新时间：2026-09-01。

## 0. 当前可用的测试 Key

当前线上环境暂未配置独立的 `ORCHESTRATOR__E2B__API_KEY`，E2B 接口会回退使用 orchestrator 的 Bearer Token。因此当前可直接使用：

```text
change-me-to-a-random-token
```

使用方式：

```bash
export E2B_API_KEY="change-me-to-a-random-token"
```

这个 key 是当前部署中的共享测试凭证，不建议用于正式生产环境。后续切换独立 key 时，只需要在 `orchestrator-service` Deployment 增加：

```yaml
- name: ORCHESTRATOR__E2B__API_KEY
  valueFrom:
    secretKeyRef:
      name: orchestrator-e2b
      key: api-key
```

并滚动更新服务即可；文档中的 SDK 调用方式不需要改变。

注意：`https://orchestrator.runlet.cn/e2b/sandboxes` 是创建接口，只接受 `POST`，直接在浏览器地址栏访问会发送 `GET`，不是正确的创建请求。

## 1. 实际访问地址

| 用途 | 地址 |
| --- | --- |
| E2B 控制面基址 | `https://orchestrator.runlet.cn/e2b` |
| E2B 创建 sandbox | `https://orchestrator.runlet.cn/e2b/sandboxes` |
| E2B 查询 sandbox | `https://orchestrator.runlet.cn/e2b/sandboxes/{sandbox_id}` |
| E2B 连接/恢复 | `https://orchestrator.runlet.cn/e2b/sandboxes/{sandbox_id}/connect` |
| E2B 暂停 | `https://orchestrator.runlet.cn/e2b/sandboxes/{sandbox_id}/pause` |
| E2B 续期 | `https://orchestrator.runlet.cn/e2b/sandboxes/{sandbox_id}/timeout` |
| E2B 永久删除 | `https://orchestrator.runlet.cn/e2b/sandboxes/{sandbox_id}` |
| sandbox envd 数据面 | `https://49983-{sandbox_id}.sandbox.runlet.cn` |
| 私有管理 API | `https://orchestrator.runlet.cn/api/v1` |
| 健康检查 | `https://orchestrator.runlet.cn/health` |

例如 sandbox ID 为 `abc12345` 时，envd 数据面地址为：

```text
https://49983-abc12345.sandbox.runlet.cn
```

`49983` 是当前 envd 监听端口。上游不需要直接拼接或调用 `process.Process/Start`，官方 SDK 会自动根据创建响应构造数据面地址并处理 Connect RPC 协议。

## 2. 快速开始：官方 E2B Python SDK

### 2.1 安装

```bash
pip install e2b
```

当前线上链路已使用 `e2b` Python SDK 2.46.0 完成端到端验证。上游可以使用兼容的 2.x 版本。

### 2.2 同步调用

```python
from e2b import Sandbox

E2B_API_KEY = "change-me-to-a-random-token"
SDK_CONFIG = {
    "api_url": "https://orchestrator.runlet.cn/e2b",
    "domain": "sandbox.runlet.cn",
    "api_key": E2B_API_KEY,
    "request_timeout": 60,
}

sandbox = Sandbox.create(
    template="sandbox-agent",
    timeout=300,
    metadata={"job_id": "1001"},
    envs={"JOB_ID": "1001"},
    **SDK_CONFIG,
)

print("sandbox_id:", sandbox.sandbox_id)

result = sandbox.commands.run("printf 'hello from sandbox'")
print(result.stdout)

sandbox.files.write("/workspace/hello.txt", "persistent workspace data")
print(sandbox.files.read("/workspace/hello.txt"))

# 释放运行资源，但保留 workspace PVC。
sandbox.pause(keep_memory=False)

# 后续重新连接。connect 会自动恢复已暂停 sandbox。
connected = Sandbox.connect(sandbox.sandbox_id, **SDK_CONFIG)
print(connected.files.read("/workspace/hello.txt"))

connected.set_timeout(600)

# 确认不再需要时永久删除 sandbox、PVC、Service 和 Ingress。
connected.kill()
```

### 2.3 异步调用

```python
from e2b import AsyncSandbox

E2B_API_KEY = "change-me-to-a-random-token"
SDK_CONFIG = {
    "api_url": "https://orchestrator.runlet.cn/e2b",
    "domain": "sandbox.runlet.cn",
    "api_key": E2B_API_KEY,
    "request_timeout": 60,
}

sandbox = await AsyncSandbox.create(
    template="sandbox-agent",
    timeout=300,
    metadata={"job_id": "1001"},
    envs={"JOB_ID": "1001"},
    **SDK_CONFIG,
)

try:
    result = await sandbox.commands.run("python -c 'print(1 + 1)'")
    print(result.stdout)
finally:
    await sandbox.kill()
```

### 2.4 不要用 context manager 自动结束 sandbox

官方 SDK 的 context manager 退出时会调用 `kill()`。在当前 Litterbox 语义中，`kill()` 是永久删除，会删除 workspace PVC。

需要保留 workspace 时，应显式调用 `pause(keep_memory=False)`：

```python
# 不推荐：退出 with 会永久删除 sandbox 和 workspace PVC。
with Sandbox.create(template="sandbox-agent", **SDK_CONFIG) as sandbox:
    sandbox.files.write("/workspace/data.txt", "keep me")
```

## 3. Template 与 workspace

E2B SDK 的 `Sandbox.create()` 只选择已有 Template，不负责创建 Template。Template 和 workspace 策略由 Litterbox 私有管理 API 配置。

当前线上可用的示例 Template：

| Template ID | 镜像 | workspace |
| --- | --- | --- |
| `sandbox-agent` | `registry.runlet.cn/litterbox/sandbox-agent:python3.12-nodejs26-slim-amd64` | `/workspace`，1Gi，`litterbox-workspace-lvm` |
| `testagent` | `ubuntu:24.04` | `/workspace`，1Gi，`litterbox-workspace-lvm` |
| `hermes` | `registry.runlet.cn/pai/hermes-agent:0.17.0-saas-acp` | 未配置独立 workspace |
| `test` | `registry.runlet.cn/pai/agent:1.0` | 未配置独立 workspace |

### 3.1 查询 Template

```http
GET https://orchestrator.runlet.cn/api/v1/templates
Authorization: Bearer <ORCHESTRATOR_BEARER_TOKEN>
```

```bash
curl -sS \
  -H "Authorization: Bearer $ORCHESTRATOR_BEARER_TOKEN" \
  https://orchestrator.runlet.cn/api/v1/templates
```

### 3.2 创建带 workspace 的 Template

```http
POST https://orchestrator.runlet.cn/api/v1/templates
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
| `storage_class` | string/null | 默认使用 `litterbox-workspace-lvm` |

### 3.3 workspace 生命周期

- 每个 sandbox 拥有独立 PVC。
- `pause(keep_memory=False)` 或私有 API `suspend` 只将 Deployment 缩容到 0，保留 PVC。
- `connect()` 或私有 API `resume` 会重新挂载原 PVC。
- E2B `kill()` 或私有 API `DELETE /api/v1/sandboxes/{id}` 会永久删除 PVC。
- Template 的 workspace 配置影响后续新建 sandbox，不会自动修改已有 PVC。

## 4. E2B 控制面接口

E2B 控制面不返回 Litterbox 的 `{success, data}` 包装，而是返回 E2B 风格的原生对象。

### 4.1 创建 sandbox

```http
POST https://orchestrator.runlet.cn/e2b/sandboxes
X-API-Key: <E2B_API_KEY>
Content-Type: application/json
```

```json
{
  "templateID": "sandbox-agent",
  "timeout": 300,
  "metadata": {"job_id": "1001"},
  "envVars": {"JOB_ID": "1001"},
  "secure": true,
  "allow_internet_access": true
}
```

curl：

```bash
curl -sS -X POST \
  https://orchestrator.runlet.cn/e2b/sandboxes \
  -H "X-API-Key: $E2B_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "templateID": "sandbox-agent",
    "timeout": 300,
    "metadata": {"job_id": "1001"},
    "envVars": {"JOB_ID": "1001"},
    "secure": true,
    "allow_internet_access": true
  }'
```

成功响应：

```json
{
  "templateID": "sandbox-agent",
  "sandboxID": "abc12345",
  "clientID": "litterbox",
  "domain": "sandbox.runlet.cn",
  "envdVersion": "0.1.0",
  "envdAccessToken": "<ENVD_ACCESS_TOKEN>",
  "trafficAccessToken": null
}
```

创建响应中的 `envdAccessToken` 由 SDK 自动用于 sandbox 数据面。上游不需要自行拼接数据面认证头。

### 4.2 查询 sandbox

```http
GET https://orchestrator.runlet.cn/e2b/sandboxes/{sandbox_id}
X-API-Key: <E2B_API_KEY>
```

```bash
curl -sS \
  -H "X-API-Key: $E2B_API_KEY" \
  https://orchestrator.runlet.cn/e2b/sandboxes/abc12345
```

响应中的 `state` 可能为：

| state | 含义 |
| --- | --- |
| `running` | Deployment 有运行中的 Pod |
| `paused` | Deployment 已缩容到 0，workspace 保留 |
| `dead` | sandbox 已退出或不可用 |

### 4.3 连接并恢复 sandbox

```http
POST https://orchestrator.runlet.cn/e2b/sandboxes/{sandbox_id}/connect
X-API-Key: <E2B_API_KEY>
Content-Type: application/json
```

```json
{"timeout": 300}
```

SDK：

```python
from e2b import Sandbox

sandbox = Sandbox.connect(
    "abc12345",
    api_url="https://orchestrator.runlet.cn/e2b",
    domain="sandbox.runlet.cn",
    api_key="<E2B_API_KEY>",
    request_timeout=60,
)
```

如果 sandbox 已暂停，`connect` 会恢复 Deployment；如果 sandbox 已被业务锁定，恢复会返回 `409`。

### 4.4 暂停 sandbox

```http
POST https://orchestrator.runlet.cn/e2b/sandboxes/{sandbox_id}/pause
X-API-Key: <E2B_API_KEY>
Content-Type: application/json
```

请求：

```json
{"memory": false}
```

SDK：

```python
sandbox.pause(keep_memory=False)
```

当前只支持文件系统级暂停。`keep_memory=True` 会返回 `409`，因为当前项目没有实现内存快照。

### 4.5 修改 timeout

```http
POST https://orchestrator.runlet.cn/e2b/sandboxes/{sandbox_id}/timeout
X-API-Key: <E2B_API_KEY>
Content-Type: application/json
```

```json
{"timeout": 600}
```

SDK：

```python
sandbox.set_timeout(600)
```

当前 TTL 规则：`0` 表示不超时；`60..86400` 表示秒数；负数非法。部分 E2B SDK 版本在 `Sandbox.create(timeout=0)` 时会使用 SDK 默认值，需要永久保留时建议创建后调用 `sandbox.set_timeout(0)`。

### 4.6 永久删除 sandbox

```http
DELETE https://orchestrator.runlet.cn/e2b/sandboxes/{sandbox_id}
X-API-Key: <E2B_API_KEY>
```

```python
sandbox.kill()
```

这是不可恢复操作，会删除 Deployment、workspace PVC、sandbox expose 对应的 Service/Ingress 和 TTL 调度记录。接口成功返回 `204 No Content`。

## 5. E2B envd 数据面

### 5.1 SDK 数据面调用

以下调用会访问：

```text
https://49983-{sandbox_id}.sandbox.runlet.cn
```

```python
result = sandbox.commands.run("pwd && ls -la /workspace")
print(result.stdout)

sandbox.files.write("/workspace/result.json", '{"ok": true}')
content = sandbox.files.read("/workspace/result.json")
print(content)
```

官方 SDK 会处理 envd 的 Connect RPC framing。不要把 `Process/Start` 当成普通 JSON REST 接口直接发送裸 JSON；这会得到协议错误或 `415`。

### 5.2 数据面地址和鉴权

SDK 创建 sandbox 后会从响应取得：

```text
domain     = sandbox.runlet.cn
envd token = envdAccessToken
envd port  = 49983
```

数据面请求通过下面的 Host 路由到对应 sandbox：

```text
Host: 49983-{sandbox_id}.sandbox.runlet.cn
```

如果使用自定义 HTTP 客户端访问简单接口，可使用：

```http
X-Access-Token: <ENVD_ACCESS_TOKEN>
```

例如检查 envd：

```bash
curl -i \
  "https://49983-abc12345.sandbox.runlet.cn/health" \
  -H "X-Access-Token: $E2B_API_KEY"
```

生产上优先使用官方 SDK，避免自行实现 Connect RPC、流式响应和 sandbox hostname 路由。

### 5.3 旧的 path-based envd 代理

编排器仍保留内部 path-based 代理，地址为：

```text
https://orchestrator.runlet.cn/api/v1/sandboxes/{sandbox_id}/envd/{envd_path}
```

示例：

```text
https://orchestrator.runlet.cn/api/v1/sandboxes/abc12345/envd/health
```

该路径使用私有 API 的 Bearer Token，主要用于诊断和兼容旧客户端。官方 E2B SDK 不应使用该路径作为主数据面地址。

## 6. 业务锁定

业务锁用于标记当前 sandbox 存在业务异常。被锁定后：

- 可以被 TTL 自动暂停到 0。
- 可以执行查询、日志等允许的管理操作。
- 恢复操作会被拒绝。
- 删除操作仍然允许，用于最终清理。

加锁：

```http
POST https://orchestrator.runlet.cn/api/v1/sandboxes/{sandbox_id}/lock
Authorization: Bearer <ORCHESTRATOR_BEARER_TOKEN>
```

解锁：

```http
POST https://orchestrator.runlet.cn/api/v1/sandboxes/{sandbox_id}/unlock
Authorization: Bearer <ORCHESTRATOR_BEARER_TOKEN>
```

SDK 没有标准的 lock/unlock 方法，因此该能力只能通过私有管理 API 使用。解锁后，E2B `Sandbox.connect()` 才可以恢复 sandbox。

## 7. 私有管理 API

私有 API 的基址为：

```text
https://orchestrator.runlet.cn/api/v1
```

鉴权：

```http
Authorization: Bearer <ORCHESTRATOR_BEARER_TOKEN>
```

私有 API 返回统一包装：

```json
{
  "success": true,
  "message": "...",
  "data": {}
}
```

### 7.1 Sandbox 管理

| 方法 | 实际地址 | 用途 |
| --- | --- | --- |
| `POST` | `https://orchestrator.runlet.cn/api/v1/sandboxes` | 使用私有请求模型创建 sandbox |
| `GET` | `https://orchestrator.runlet.cn/api/v1/sandboxes` | 分页查询 sandbox |
| `POST` | `https://orchestrator.runlet.cn/api/v1/sandboxes/query` | 按条件查询 |
| `GET` | `https://orchestrator.runlet.cn/api/v1/sandboxes/{id}` | 获取详情 |
| `PATCH` | `https://orchestrator.runlet.cn/api/v1/sandboxes/{id}` | 更新名称/metadata 等 |
| `DELETE` | `https://orchestrator.runlet.cn/api/v1/sandboxes/{id}` | 永久删除 |
| `POST` | `https://orchestrator.runlet.cn/api/v1/sandboxes/{id}/suspend` | 暂停并保留 PVC |
| `POST` | `https://orchestrator.runlet.cn/api/v1/sandboxes/{id}/resume` | 恢复；锁定时拒绝 |
| `POST` | `https://orchestrator.runlet.cn/api/v1/sandboxes/{id}/lock` | 加业务锁 |
| `POST` | `https://orchestrator.runlet.cn/api/v1/sandboxes/{id}/unlock` | 解业务锁 |
| `POST` | `https://orchestrator.runlet.cn/api/v1/sandboxes/{id}/renew` | 续期 |
| `PUT` | `https://orchestrator.runlet.cn/api/v1/sandboxes/{id}/ttl` | 设置 TTL |
| `GET` | `https://orchestrator.runlet.cn/api/v1/sandboxes/{id}/ttl` | 查询 TTL |
| `GET` | `https://orchestrator.runlet.cn/api/v1/sandboxes/{id}/status` | 查询运行状态 |

私有 API 的 `DELETE` 与 E2B `kill()` 相同，都是永久删除；暂停必须使用 `suspend` 或 E2B `pause(memory=false)`。

### 7.2 Template 管理

| 方法 | 实际地址 | 用途 |
| --- | --- | --- |
| `POST` | `https://orchestrator.runlet.cn/api/v1/templates` | 创建 Template |
| `GET` | `https://orchestrator.runlet.cn/api/v1/templates` | 查询 Template 列表 |
| `GET` | `https://orchestrator.runlet.cn/api/v1/templates/{id}` | 获取 Template |
| `PATCH` | `https://orchestrator.runlet.cn/api/v1/templates/{id}` | 更新 Template |
| `DELETE` | `https://orchestrator.runlet.cn/api/v1/templates/{id}` | 删除 Template |

### 7.3 Expose 管理

| 方法 | 实际地址 | 用途 |
| --- | --- | --- |
| `POST` | `https://orchestrator.runlet.cn/api/v1/sandboxes/{id}/exposes` | 暴露 sandbox 端口 |
| `GET` | `https://orchestrator.runlet.cn/api/v1/sandboxes/{id}/exposes` | 查询 sandbox 的 expose |
| `GET` | `https://orchestrator.runlet.cn/api/v1/exposes/{expose_id}` | 查询 expose |
| `DELETE` | `https://orchestrator.runlet.cn/api/v1/exposes/{expose_id}` | 删除 expose |

创建 HTTP expose：

```json
{
  "name": "web",
  "protocol": "http",
  "internal_port": 8080,
  "domain": "",
  "path": "/"
}
```

当 `domain` 为空时，系统会生成类似：

```text
https://8080-{sandbox_id}.runlet.cn
```

### 7.4 Warm Pool

| 方法 | 实际地址 | 用途 |
| --- | --- | --- |
| `POST` | `https://orchestrator.runlet.cn/api/v1/pools/{template_id}` | 创建/启用 pool |
| `GET` | `https://orchestrator.runlet.cn/api/v1/pools` | 查询所有 pool |
| `GET` | `https://orchestrator.runlet.cn/api/v1/pools/{template_id}` | 查询指定 pool |
| `PUT` | `https://orchestrator.runlet.cn/api/v1/pools/{template_id}` | 更新 pool |
| `DELETE` | `https://orchestrator.runlet.cn/api/v1/pools/{template_id}` | 删除 pool |

### 7.5 Webhook

| 方法 | 实际地址 | 用途 |
| --- | --- | --- |
| `POST` | `https://orchestrator.runlet.cn/api/v1/webhooks` | 创建 webhook |
| `GET` | `https://orchestrator.runlet.cn/api/v1/webhooks` | 查询 webhook |
| `GET` | `https://orchestrator.runlet.cn/api/v1/webhooks/{id}` | 获取 webhook |
| `PATCH` | `https://orchestrator.runlet.cn/api/v1/webhooks/{id}` | 更新 webhook |
| `DELETE` | `https://orchestrator.runlet.cn/api/v1/webhooks/{id}` | 删除 webhook |

## 8. 当前支持范围

### 已支持

- E2B `Sandbox.create`
- E2B `Sandbox.connect`
- E2B `Sandbox.pause(keep_memory=False)`
- E2B `Sandbox.set_timeout`
- E2B `Sandbox.kill`
- E2B sandbox 查询
- envd 命令执行
- envd 文件读写
- envd PTY/流式 Connect RPC
- sandbox hostname 数据面路由
- workspace PVC 挂载
- workspace 文件在暂停/恢复后的持久化
- Template workspace 默认配置
- sandbox 业务锁

### 暂不支持

| E2B 能力 | 当前状态 |
| --- | --- |
| `pause(keep_memory=True)` 内存快照 | 不支持，返回 `409` |
| snapshots | 不支持 |
| fork | 不支持 |
| E2B volumes API | 不支持；workspace 通过 Template 配置 |
| Template build | 不支持；使用已有容器镜像 |
| network allow/deny 策略 | 不支持；`allow_internet_access=false` 会被拒绝 |
| traffic proxy token | 当前返回 `null` |

## 9. 错误与排查

### E2B 控制面错误

| HTTP 状态 | 含义 |
| --- | --- |
| `400` | 请求参数非法或请求了不支持的能力 |
| `401` | `X-API-Key` 缺失或错误 |
| `404` | sandbox/template 不存在，或 E2B 控制面未启用 |
| `409` | 当前状态不允许操作，例如锁定 sandbox 恢复，或请求内存快照暂停 |
| `500` | 编排器或 Kubernetes 操作失败 |

### 数据面错误

| HTTP/SDK 错误 | 常见原因 |
| --- | --- |
| TLS `NotValidForName` | sandbox wildcard 入口或证书未配置；当前线上域名应使用 `*.sandbox.runlet.cn` |
| `401 Unauthorized` | SDK 未拿到 `envdAccessToken`，或直接 HTTP 请求缺少 `X-Access-Token` |
| `409 sandbox is not running` | sandbox 已暂停，需要先 `Sandbox.connect()` |
| `502 envd upstream unavailable` | Pod 尚未 ready、envd 未启动或 Pod 地址不可用 |
| `503 sandbox pod address unavailable` | sandbox 没有可用的 Running Pod |
| `415` / Connect 协议错误 | 将 envd 的 Connect RPC 当成裸 JSON REST 调用 |

### workspace PVC Pending

检查：

```bash
kubectl get pod -A -l component=sandbox -o wide
kubectl get pvc -A
kubectl describe pod -n default <pod-name>
kubectl get lvmnode -n openebs
```

重点确认：

- `litterbox-workspace-lvm` 是否有可用容量。
- `LVMNode` 是否能看到 `litterbox-workspace-vg`。
- PVC 是否已经 `Bound`。
- sandbox Pod 是否因为 `WaitForFirstConsumer` 或存储不足而 Pending。

## 10. 健康检查与 OpenAPI

健康检查：

```bash
curl -sS https://orchestrator.runlet.cn/health
```

其他运维地址：

| 方法 | 实际地址 | 用途 |
| --- | --- | --- |
| `GET` | `https://orchestrator.runlet.cn/` | 服务根路径 |
| `GET` | `https://orchestrator.runlet.cn/metrics` | Prometheus 文本指标 |
| `GET` | `https://orchestrator.runlet.cn/api/v1/metrics/snapshot` | JSON 指标快照 |

OpenAPI：

```text
https://orchestrator.runlet.cn/openapi.json
```

Swagger UI：

```text
https://orchestrator.runlet.cn/docs
```

当前 OpenAPI 主要描述私有 `/api/v1` 路由；E2B 路由的上游使用方式以本文档和 E2B SDK 示例为准。
