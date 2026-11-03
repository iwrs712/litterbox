> **历史记录**：本文写于 2026-11-03，当时沙箱仍由 Deployment 管理。当前架构已改为 `Sandbox` / `SandboxPool` CRD + 控制器；部署步骤以 `controller/README.md` 和 `docs/development.md` 为准。

# 本地 Colima + k3s 部署与 E2B 数据面验证记录

日期：2026-11-03  
环境：macOS 15.8.1 / Apple M1 Pro / 32 GB  
结论：**Kata Containers 在这台机器上不可用；改用 runc 后，E2B 控制面和 envd 数据面均已在本地跑通。**

## 1. 环境与结论

| 项目 | 值 |
| --- | --- |
| 主机 | MacBook Pro，Apple M1 Pro，macOS 15.8.1 |
| 容器运行时 | Colima 0.10.3（VM 类型 vz，aarch64） |
| Kubernetes | k3d 5.9.0，k3s v1.35.5+k3s1 |
| sandbox runtime | runc（默认），未启用 Kata |
| envd | 本地构建 `linux/arm64` 静态二进制 |
| 存储 | k3s `local-path` |
| E2B SDK | `e2b==2.46.0` |

验证结果：

```text
creating sandbox...
sandbox_id: ce8c709b
sdk data-plane url: https://49983-ce8c709b.localhost
opening envd workspace gate via: http://127.0.0.1:8080/api/v1/sandboxes/ce8c709b/envd
restore: {'restored': True, 'result': {'exit_code': 0, 'elapsed_ms': 0, 'output': 'no durable copy configured'}}
connecting through path proxy...
stdout: Linux ce8c709b-7d5b889cfd-wv447 6.8.0-117-generic ... aarch64 aarch64 aarch64 GNU/Linux
root
/
exit_code: 0
file: hello from e2b sdk
entries: [EntryInfo(name='hello.txt', type=<FileType.FILE: 'file'>, path='/workspace/hello.txt', ...)]
E2E OK
```

补充验证了暂停/恢复后的 workspace 持久化：

```text
pausing...
resuming...
restore: {'restored': True, 'result': {'exit_code': 0, 'elapsed_ms': 0, 'output': 'no durable copy configured'}}
file after resume: hello from e2b sdk
PERSIST OK
```

`pause(keep_memory=False)` 会把 Deployment 缩容到 0，恢复后 PVC 和文件仍在；新的 envd 进程需要再次调用 `/v1/workspace/restore` 开门。

TTL 验证：把 sandbox TTL 改成 5 秒后，两个 sandbox 的 Deployment 都自动缩容到 0，Pod 进入 Terminating：

```text
ce8c709b replicas=0 ready= suspended=2026-11-03T08:05:56Z
f422ae2d replicas=0 ready= suspended=2026-11-03T08:05:05Z
```

## 2. Kata Containers 为什么不可用

Kata 要求每个节点有可用的 `/dev/kvm`；如果节点本身是虚拟机，则宿主机必须支持嵌套虚拟化。

- 本机是 **M1 Pro**。Apple Silicon 的嵌套虚拟化从 **M3 起、macOS 15+** 才支持。
- Colima 的嵌套虚拟化依赖 `krunkit` VM 类型，而 krunkit 文档明确要求 **M3 或更新 CPU + macOS 15+**。
- 实测 Colima VM 内：

```bash
colima ssh -- ls -l /dev/kvm
# ls: cannot access '/dev/kvm': No such file or directory
```

- 当前 OrbStack VM 内同样没有 `/dev/kvm`。
- Kata 的 VMM（QEMU/Cloud Hypervisor/Dragonball/Firecracker）都依赖 KVM/HVF 硬件加速，QEMU TCG 纯软件模拟不是受支持的替代方案。

因此本地只能让 sandbox Pod 使用 runc。orchestrator 的 runtime class 逻辑是“RuntimeClass 存在才使用”，把 `runtime_class` 设为空即可，不影响其余功能。

**以后切换回 Kata：** orchestrator 侧只需改 `ORCHESTRATOR__KUBERNETES__RUNTIME_CLASS`（或 `config.toml` 的 `runtime_class`）；但目标集群必须已经安装 Kata containerd shim、guest kernel/rootfs 并创建了对应 RuntimeClass，这部分不是改配置就能出现的。

## 3. 部署步骤

### 3.1 启动 Colima 和 k3d

```bash
brew install colima k3d
colima start --cpu 4 --memory 8 --disk 60
k3d cluster create litterbox \
  --servers 1 --agents 1 --wait --timeout 300s \
  --k3s-arg '--disable=traefik@server:0'
kubectl get nodes
```

### 3.2 构建 arm64 envd

`envd/Makefile` 只有 `build-linux-amd64`，本地 arm64 节点需要手动构建：

```bash
cd envd
CGO_ENABLED=0 GOOS=linux GOARCH=arm64 \
  go build -trimpath -ldflags='-s -w' \
  -o bin/envd-linux-arm64 ./cmd/envd
```

### 3.3 构建 orchestrator 镜像

Dockerfile 写死了清华 PyPI 镜像，在 Colima 里拉不到 `celery`。临时把索引换成官方 PyPI 构建（不改仓库 Dockerfile）：

```bash
cd orchestrator
sed 's#https://pypi.tuna.tsinghua.edu.cn/simple#https://pypi.org/simple#' \
  Dockerfile > Dockerfile.local
docker build --platform linux/arm64 \
  -f Dockerfile.local -t litterbox/orchestrator:local .
rm Dockerfile.local
k3d image import litterbox/orchestrator:local -c litterbox
```

### 3.4 把 envd 放进节点并打标签

k3d 节点是容器，直接复制二进制到节点文件系统，模拟 node installer：

```bash
for n in k3d-litterbox-server-0 k3d-litterbox-agent-0; do
  docker exec "$n" mkdir -p /opt/litterbox/bin
  docker cp envd/bin/envd-linux-arm64 "$n:/opt/litterbox/bin/envd"
  docker exec "$n" chmod +x /opt/litterbox/bin/envd
done
kubectl label node k3d-litterbox-server-0 k3d-litterbox-agent-0 \
  litterbox.io/envd-version=0.1.0 --overwrite
```

### 3.5 部署 Redis 和 orchestrator

需要的资源包括：

- `litterbox` namespace、ServiceAccount、ClusterRole/Binding（orchestrator 需要操作 default namespace 的 Deployment/Pod/PVC/Service/Ingress/ConfigMap/Secret，以及读取 Node/RuntimeClass）。
- Redis Deployment + Service。
- orchestrator `api` 与 `worker` 两个 Deployment（同一镜像，`ORCHESTRATOR_ROLE` 不同）。
- 关键环境变量：

```yaml
ORCHESTRATOR__KUBERNETES__NAMESPACE: default
ORCHESTRATOR__KUBERNETES__RUNTIME_CLASS: ""
ORCHESTRATOR__KUBERNETES__IMAGE_PULL_SECRET: ""
ORCHESTRATOR__WORKSPACE__STORAGE_CLASS: local-path
ORCHESTRATOR__ENVD__ENABLED: "true"
ORCHESTRATOR__ENVD__VERSION: "0.1.0"
ORCHESTRATOR__ENVD__HOST_BINARY_PATH: /opt/litterbox/bin/envd
ORCHESTRATOR__ENVD__CONTAINER_BINARY_PATH: /opt/litterbox/envd/envd
ORCHESTRATOR__E2B__ENABLED: "true"
ORCHESTRATOR__E2B__API_KEY: local-e2b-key
ORCHESTRATOR__E2B__DOMAIN: localhost
ORCHESTRATOR__AUTH__BEARER_TOKEN: ""
ORCHESTRATOR__CELERY__BROKER_URL: redis://redis:6379/2
ORCHESTRATOR__CELERY__RESULT_BACKEND: redis://redis:6379/2
ORCHESTRATOR__SANDBOX__BASE_DOMAIN: localhost
```

完整 manifest 见文末附录 A。

### 3.6 暴露 API 并创建模板

```bash
kubectl -n litterbox port-forward svc/orchestrator 8080:8080
```

另开终端：

```bash
curl -sS http://127.0.0.1:8080/health

curl -sS -X POST http://127.0.0.1:8080/api/v1/templates \
  -H 'Content-Type: application/json' \
  -d '{
    "id":"ubuntu","name":"ubuntu","image":"ubuntu:22.04",
    "command":"sleep infinity","cpu_millicores":500,"memory_mb":512,
    "ttl_seconds":3600,
    "workspace":{"enabled":true,"size":"1Gi","storage_class":"local-path"}
  }'
```

### 3.7 用 E2B SDK 创建并调用数据面

```python
import httpx
from e2b import Sandbox

API = "http://127.0.0.1:8080"
CFG = dict(api_url=f"{API}/e2b", api_key="local-e2b-key",
           domain="localhost", request_timeout=60)

sandbox = Sandbox.create(template="ubuntu", timeout=600, **CFG)
sandbox_id = sandbox.sandbox_id
path_url = f"{API}/api/v1/sandboxes/{sandbox_id}/envd"

# 打开 envd 的 workspace 门禁
httpx.post(f"{path_url}/v1/workspace/restore", json={}, timeout=30).raise_for_status()

s = Sandbox.connect(sandbox_id, sandbox_url=path_url, **CFG)
print(s.commands.run("uname -a && whoami").stdout)
s.files.write("/workspace/hello.txt", "hello from e2b sdk\n")
print(s.files.read("/workspace/hello.txt"))
print(s.files.list("/workspace"))
```

### 3.8 启动 dashboard

dashboard 使用 `VITE_API_BASE_URL` 访问 orchestrator。本地用单独的 `.env.local`（git 忽略），不修改 `.env.example`，也不影响线上配置：

```bash
cd dashboard
npm install --cache /tmp/npm-cache-litterbox
npm run dev:local
# http://127.0.0.1:5173
```

`dev:local` 会：

1. 如果 `.env.local` 不存在，从 `.env.local.example` 生成；
2. 检查 `VITE_API_BASE_URL/health`，不可达时提示先启动 orchestrator port-forward；
3. 固定 Vite 端口 `5173`（可用 `VITE_PORT` 覆盖）。

本地 `.env.local`：

```dotenv
VITE_API_BASE_URL=http://127.0.0.1:8080
VITE_API_BEARER_TOKEN=
VITE_ENVD_AUTO_RESTORE=true
```

`VITE_ENVD_AUTO_RESTORE=true` 只对本地生效：终端和命令调用前会先看 envd `/health`，如果 `workspace` 是 `restoring`，就调用一次 `POST /v1/workspace/restore`（本地无对象存储，body 为 `{}`）。线上不设置这个变量，因此不会改变现有行为。

验证 Vite 实际加载到的值：

```bash
node --input-type=module -e \
  "import {loadEnv} from 'vite'; const e=loadEnv('development', process.cwd(), ''); console.log(e.VITE_API_BASE_URL, e.VITE_API_BEARER_TOKEN)"
# http://127.0.0.1:8080
```

### 3.9 envd node installer 验证

仓库里的 `envd/deploy/node-installer` 逻辑是正常的：init container 把镜像内的 `/payload/envd` 原子复制到节点 `/opt/litterbox/bin/envd`，ready 容器检查可执行后常驻。

本地验证方式：用 arm64 测试镜像、`nodeSelector: kubernetes.io/arch=arm64` 和测试路径 `/opt/litterbox/installer-test` 应用一个临时 DaemonSet，两个 k3d 节点都成功安装，`envd --help` 可执行；验证后已删除测试 DaemonSet 和测试文件。

但仓库原始 manifest 不能直接用于这台 M1：

- `nodeSelector` 要求 `katacontainers.io/kata-runtime=true` 且 `kubernetes.io/arch=amd64`；
- Dockerfile 硬编码 `GOARCH=amd64`，Makefile 也只构建 `-amd64` 镜像；
- DaemonSet 不负责给节点打 `litterbox.io/envd-version` 标签，而 orchestrator 启用 envd 注入时会用这个标签做 nodeSelector；
- 镜像名没有 registry 前缀，也没有配置 `imagePullSecrets`。

因此本地实际使用的是 `docker cp` 手动安装；真实 amd64 Kata 节点上使用原始 installer 时，需要自行构建/推送镜像、打版本标签，并确保镜像可拉取。

## 4. envd workspace 门禁是什么

envd 启动时 workspace 门禁默认关闭。原因是 `/workspace` 被视为对象存储的工作副本：新的 envd 进程出现时（新建 Pod、暂停后恢复、容器重启），本地 `/workspace` 可能是空的或旧的，必须先执行 restore，才能安全地提供命令和文件接口。

门禁期间，除以下路由外，所有接口返回 503 `restoring_workspace`：

- `GET /health`
- `POST /v1/workspace/restore`
- skills 相关路由
- 文件删除（`Filesystem/Remove`）

`POST /v1/workspace/restore` 的两种模式：

| 请求体 | 行为 |
| --- | --- |
| `{"bucket": "...", "prefix": "workspaces/<uuid>/", "endpoint": "...", "credentials": {...}}` | 用 rclone 从对象存储把租户的 `proj-*` 目录恢复到 `/workspace`，使用 `--ignore-existing`，不覆盖本地更新的文件 |
| `{}` | 本地/无对象存储模式：不执行任何复制，直接开门，返回 `no durable copy configured` |

当前仓库里的 orchestrator 只负责通过 `postStart` 启动 envd，**没有**调用 `/v1/workspace/restore`。因此：

- E2B SDK 和 Dashboard 直接访问数据面时，新 Pod/恢复后的 Pod 会先收到 503，必须由某个调用方完成 restore；
- 线上如果工作正常，说明生产环境有仓库之外的调用方（workspace/session 管理器、sandbox 入口脚本等）在调用 restore，并传入真实的对象存储配置；
- 本地没有对象存储，所以用 `{}` 开门即可。Dashboard 的本地自动 restore 和 E2E 脚本都是这个用法。

**注意：** `{}` 只开门，不做数据恢复。如果生产环境接通了对象存储，不能用空请求代替真实 restore，否则命令可能在未恢复的 workspace 上运行。

## 5. 遇到的问题

| # | 现象 | 原因 | 处理 |
|---|---|---|---|
| 1 | Colima VM 内没有 `/dev/kvm` | M1 Pro 不支持嵌套虚拟化；krunkit 需要 M3+ / macOS 15+ | 本地改用 runc；Kata 留到支持 KVM 的 Linux 主机验证 |
| 2 | 构建 orchestrator 时 `celery` 找不到 | Dockerfile 的 `PIP_INDEX_URL` 指向清华镜像，Colima 内不可达 | 临时 Dockerfile 改用 `https://pypi.org/simple` |
| 3 | `docker build -f /tmp/Dockerfile ...` 报 xattr/找不到文件 | BuildKit 对 context 外文件处理异常，`-f` 又相对当前目录解析 | 把临时 Dockerfile 放到 build context 内，`-f orchestrator/Dockerfile.local orchestrator` |
| 4 | E2B SDK 请求 `POST /e2b/v2/sandboxes` 返回 404，随后 `KeyError: 'code'` | 最新 `e2b`（2.62.0）使用 `/v2/sandboxes`；Litterbox 实现的是旧版 `/sandboxes` | 固定 `e2b==2.46.0`，与项目文档验证版本一致 |
| 5 | envd 返回 503 `the sandbox workspace has not been restored yet` | envd 启动后 workspace 门禁默认关闭，需要调用 `/v1/workspace/restore` | 通过路径代理 `POST /v1/workspace/restore`，body 为 `{}`；每个新 Pod 都要重新调用 |
| 6 | SDK 默认数据面地址 `https://49983-{id}.localhost` 无法在本机使用 | 需要 443 端口、通配 DNS 和受信任的 TLS 证书；macOS 非 root 绑定 443 也受限 | 用 SDK 的 `sandbox_url` 指向 Litterbox 路径代理，走 HTTP；该参数在 SDK 中已标记 deprecated，仅用于本地验证 |
| 7 | `envd` 的 Makefile 只有 amd64 目标 | 脚本默认按生产 amd64 节点构建 | 手动 `GOOS=linux GOARCH=arm64 go build` |
| 8 | sandbox Pod 调度后找不到 envd 二进制 | orchestrator 通过 hostPath 读取 `/opt/litterbox/bin/envd`，普通节点没有该文件 | k3d 环境用 `docker cp` 复制到节点并给节点打 `litterbox.io/envd-version=0.1.0` 标签 |
| 9 | workspace PVC Pending | 默认 StorageClass `litterbox-workspace-lvm` 本地不存在 | 覆盖 `ORCHESTRATOR__WORKSPACE__STORAGE_CLASS=local-path`，或模板 workspace 指定 `local-path` |
| 10 | orchestrator 无法创建沙箱资源 | 默认 ServiceAccount 没有 RBAC 权限 | 增加 ClusterRole/Binding（见附录 A） |
| 11 | `npm install` 报 `EACCES`，路径 `~/.npm/_cacache` | 全局 npm 缓存目录存在权限/残留问题 | 用独立缓存：`npm install --cache /tmp/npm-cache-litterbox` |
| 12 | Vite 自动监听 5175 而不是 5173 | 5173 被占用时 Vite 自动递增端口 | `dev:local` 固定 `--port 5173 --strictPort`；可用 `VITE_PORT` 覆盖 |
| 13 | worker Pod 是 Running，但 sandbox 已过期仍不暂停 | 启动时 Redis 未就绪，TTL 子进程的 `pop_due()` 抛 `ConnectionError` 后退出；Celery 自己会重连，所以 Pod 仍 Running | `TTLWorker` 改为每轮捕获异常并重试（新增 `run_once` 和单元测试）；重启后 TTL 进程存在，过期 sandbox 自动缩容到 0 |
| 14 | 重启 orchestrator 后 `kubectl port-forward` 退出，dashboard/curl 报空响应 | port-forward 绑定的是旧 Pod/连接，Pod 重建后断开 | 重新执行 `kubectl -n litterbox port-forward svc/orchestrator 8080:8080` |
| 15 | Dashboard 终端页 503，`process.Process/Start` 返回 `restoring_workspace` | sandbox 暂停/恢复后 envd 新进程门禁关闭，Dashboard 没调用 restore | 本地 `VITE_ENVD_AUTO_RESTORE=true`：终端/命令前检查 `/health`，`workspace=restoring` 时调用 `POST /v1/workspace/restore`（body `{}`）；线上默认不启用 |
| 16 | 原始 envd node installer 在本地不会安装到任何节点 | DaemonSet 的 nodeSelector 是 Kata + amd64，本地是 arm64 且无 Kata；Dockerfile/Makefile 也只构建 amd64 | 本地改用 `docker cp`；用 arm64 测试镜像和 `arch=arm64` 的临时 DaemonSet 验证了 installer 逻辑本身正常；生产使用前需补 arm64 构建、版本标签和镜像拉取配置 |

## 6. 生产与本地验证的差异

| 能力 | 本地 | 生产 |
|---|---|---|
| VM 级隔离 | runc，无独立 Guest 内核 | Kata RuntimeClass |
| 数据面入口 | 路径代理 `http://.../envd/*` + SDK `sandbox_url` | `https://49983-{id}.{domain}` + 通配 TLS |
| workspace 存储 | local-path | LVM/CSI StorageClass |
| envd 安装 | 手动 `docker cp` + 节点标签 | node installer DaemonSet |
| 高可用 | 单副本 | 多副本 API/worker、Redis HA |

## 7. 清理

```bash
k3d cluster delete litterbox
colima stop
docker context use orbstack   # 如果原来使用 OrbStack
```

## 附录 A：本地 manifest（核心部分，省略了资源限制和探针）

```yaml
apiVersion: v1
kind: Namespace
metadata: {name: litterbox}
---
apiVersion: v1
kind: ServiceAccount
metadata: {name: orchestrator, namespace: litterbox}
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata: {name: litterbox-orchestrator}
rules:
  - apiGroups: [""]
    resources: [configmaps, pods, services, persistentvolumeclaims, secrets, nodes]
    verbs: [get, list, watch, create, update, patch, delete]
  - apiGroups: ["apps"]
    resources: [deployments]
    verbs: [get, list, watch, create, update, patch, delete]
  - apiGroups: ["networking.k8s.io"]
    resources: [ingresses]
    verbs: [get, list, watch, create, update, patch, delete]
  - apiGroups: ["node.k8s.io"]
    resources: [runtimeclasses]
    verbs: [get, list, watch]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata: {name: litterbox-orchestrator}
roleRef:
  {apiGroup: rbac.authorization.k8s.io, kind: ClusterRole, name: litterbox-orchestrator}
subjects:
  - {kind: ServiceAccount, name: orchestrator, namespace: litterbox}
---
apiVersion: apps/v1
kind: Deployment
metadata: {name: redis, namespace: litterbox}
spec:
  replicas: 1
  selector: {matchLabels: {app: redis}}
  template:
    metadata: {labels: {app: redis}}
    spec:
      containers:
        - name: redis
          image: redis:7-alpine
          args: [redis-server, --appendonly, "no", --maxmemory-policy, noeviction]
          ports: [{containerPort: 6379}]
---
apiVersion: v1
kind: Service
metadata: {name: redis, namespace: litterbox}
spec:
  selector: {app: redis}
  ports: [{port: 6379, targetPort: 6379}]
---
apiVersion: v1
kind: ConfigMap
metadata: {name: orchestrator-env, namespace: litterbox}
data:
  ORCHESTRATOR__KUBERNETES__NAMESPACE: "default"
  ORCHESTRATOR__KUBERNETES__RUNTIME_CLASS: ""
  ORCHESTRATOR__KUBERNETES__IMAGE_PULL_SECRET: ""
  ORCHESTRATOR__WORKSPACE__STORAGE_CLASS: "local-path"
  ORCHESTRATOR__ENVD__ENABLED: "true"
  ORCHESTRATOR__ENVD__VERSION: "0.1.0"
  ORCHESTRATOR__ENVD__HOST_BINARY_PATH: "/opt/litterbox/bin/envd"
  ORCHESTRATOR__ENVD__CONTAINER_BINARY_PATH: "/opt/litterbox/envd/envd"
  ORCHESTRATOR__E2B__ENABLED: "true"
  ORCHESTRATOR__E2B__API_KEY: "local-e2b-key"
  ORCHESTRATOR__E2B__DOMAIN: "localhost"
  ORCHESTRATOR__AUTH__BEARER_TOKEN: ""
  ORCHESTRATOR__CELERY__BROKER_URL: "redis://redis:6379/2"
  ORCHESTRATOR__CELERY__RESULT_BACKEND: "redis://redis:6379/2"
  ORCHESTRATOR__SANDBOX__BASE_DOMAIN: "localhost"
---
apiVersion: apps/v1
kind: Deployment
metadata: {name: orchestrator, namespace: litterbox}
spec:
  replicas: 1
  selector: {matchLabels: {app: orchestrator}}
  template:
    metadata: {labels: {app: orchestrator}}
    spec:
      serviceAccountName: orchestrator
      containers:
        - name: orchestrator
          image: litterbox/orchestrator:local
          imagePullPolicy: IfNotPresent
          envFrom: [{configMapRef: {name: orchestrator-env}}]
          env: [{name: ORCHESTRATOR_ROLE, value: api}]
          ports: [{containerPort: 8080}]
---
apiVersion: apps/v1
kind: Deployment
metadata: {name: orchestrator-worker, namespace: litterbox}
spec:
  replicas: 1
  selector: {matchLabels: {app: orchestrator-worker}}
  template:
    metadata: {labels: {app: orchestrator-worker}}
    spec:
      serviceAccountName: orchestrator
      containers:
        - name: worker
          image: litterbox/orchestrator:local
          imagePullPolicy: IfNotPresent
          envFrom: [{configMapRef: {name: orchestrator-env}}]
          env: [{name: ORCHESTRATOR_ROLE, value: worker}]
---
apiVersion: v1
kind: Service
metadata: {name: orchestrator, namespace: litterbox}
spec:
  selector: {app: orchestrator}
  ports: [{port: 8080, targetPort: 8080}]
```

## 附录 B：E2E 脚本

```python
import httpx
from e2b import Sandbox

API = "http://127.0.0.1:8080"
CFG = dict(api_url=f"{API}/e2b", api_key="local-e2b-key",
           domain="localhost", request_timeout=60)

sandbox = Sandbox.create(template="ubuntu", timeout=600, **CFG)
sandbox_id = sandbox.sandbox_id
path_url = f"{API}/api/v1/sandboxes/{sandbox_id}/envd"

httpx.post(f"{path_url}/v1/workspace/restore", json={}, timeout=30).raise_for_status()

s = Sandbox.connect(sandbox_id, sandbox_url=path_url, **CFG)
print(s.commands.run("uname -a && whoami && pwd").stdout)
s.files.write("/workspace/hello.txt", "hello from e2b sdk\n")
print(s.files.read("/workspace/hello.txt"))
print(s.files.list("/workspace"))
print("E2E OK")
```
