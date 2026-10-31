# envd 节点级安装与部署

envd（`sandbox-agent-go`）不再要求预制在每一个 Sandbox 镜像中。安装镜像通过
DaemonSet 把静态 amd64 二进制写入每个 Kata 节点的
`/opt/litterbox/bin/sandbox-agent`，orchestrator 再以只读 `hostPath` 把它挂载到
Sandbox 主容器的 `/opt/litterbox/envd/sandbox-agent`，并通过 `postStart` 启动。

## 组件和路径

| 项目 | 路径或名称 |
| --- | --- |
| daemon 源码 | `sandbox-agent-go/` |
| amd64 二进制 | `sandbox-agent-go/bin/sandbox-agent-linux-amd64` |
| installer Dockerfile | `sandbox-agent-go/deploy/node-installer/Dockerfile` |
| installer 镜像 | `registry.runlet.cn/litterbox/envd-node-installer:<version>-amd64` |
| DaemonSet | `litterbox/envd-node-installer` |
| 节点二进制 | `/opt/litterbox/bin/sandbox-agent` |
| 容器挂载路径 | `/opt/litterbox/envd/sandbox-agent` |

## 首次部署

### 1. 构建 daemon 和 installer 镜像

在本地执行：

```bash
cd /Users/v_chenyongjie01/personal_project/github/litterbox/sandbox-agent-go
make test
make build-linux-amd64
make build-node-installer ENVD_VERSION=0.1.4
make push-node-installer ENVD_VERSION=0.1.4
```

检查产物架构和镜像：

```bash
file bin/sandbox-agent-linux-amd64
docker buildx imagetools inspect \
  registry.runlet.cn/litterbox/envd-node-installer:0.1.4-amd64
```

### 2. 安装到所有 Kata 节点

```bash
cd /Users/v_chenyongjie01/personal_project/github/litterbox/orchestrator
ENVD_VERSION=0.1.4 ./k8s/envd/install.sh
```

安装前必须保证 `litterbox` namespace 已存在，并且其中有用于拉取私有镜像的
`harbor-pull-secret`。脚本会在变更节点标签前验证这个 Secret。

脚本依次执行：

1. 找出带有 `katacontainers.io/kata-runtime=true` 的 amd64 节点。
2. 暂时移除 `litterbox.io/envd-version`，阻止新 Sandbox 调度到安装中的节点。
3. 应用 DaemonSet，由 init container 原子替换节点二进制。
4. 等待每个目标节点上的 installer Pod Ready。
5. 添加实际的 `litterbox.io/envd-version` 标签。

installer 不需要 privileged 权限，但以 root 身份写入限定的 hostPath。常驻的 BusyBox
容器只读挂载该目录并执行 `sleep`，资源限制为 `20m CPU / 16Mi`。

### 3. 配置并更新 orchestrator

`orchestrator-service` 和 `orchestrator-worker` 使用一致的配置：

```yaml
- name: ORCHESTRATOR__ENVD__ENABLED
  value: "true"
- name: ORCHESTRATOR__ENVD__VERSION
  value: "0.1.0"
- name: ORCHESTRATOR__ENVD__HOST_BINARY_PATH
  value: /opt/litterbox/bin/sandbox-agent
- name: ORCHESTRATOR__ENVD__CONTAINER_BINARY_PATH
  value: /opt/litterbox/envd/sandbox-agent
- name: ORCHESTRATOR__ENVD__PORT
  value: "49983"
```

修改 Deployment 后重启并等待服务就绪：

```bash
kubectl -n litterbox rollout restart deployment/orchestrator-service
kubectl -n litterbox rollout restart deployment/orchestrator-worker
kubectl -n litterbox rollout status deployment/orchestrator-service --timeout=300s
kubectl -n litterbox rollout status deployment/orchestrator-worker --timeout=300s
```

必须先完成节点安装和版本标签，再启用 orchestrator 的 envd 注入，否则新 Sandbox
会按设计保持 Pending，而不会落到缺失 daemon 的节点。

## 验证

查看节点和 installer：

```bash
kubectl get nodes \
  -l katacontainers.io/kata-runtime=true \
  -L litterbox.io/envd-version
kubectl -n litterbox get daemonset,pods -l app.kubernetes.io/name=envd-node-installer -o wide
```

创建一个不包含 envd 的普通 Sandbox 镜像后，检查 Deployment 注入：

```bash
SBX=<sandbox-id>
kubectl -n default get deployment "$SBX" \
  -o jsonpath='{.spec.template.spec.nodeSelector}{"\n"}'
kubectl -n default get deployment "$SBX" \
  -o jsonpath='{.metadata.annotations.litterbox\.io/envd-version}{"\n"}'
kubectl -n default exec deployment/"$SBX" -- \
  /opt/litterbox/envd/sandbox-agent --help
```

最后通过 E2B SDK执行一次命令和文件读写。成功即证明控制面代理、hostPath 注入和 envd
启动链路都已生效。

## 升级 daemon

例如升级到 `0.1.1`：

```bash
cd /Users/v_chenyongjie01/personal_project/github/litterbox/sandbox-agent-go
make test
make build-linux-amd64
make build-node-installer ENVD_VERSION=0.1.1
make push-node-installer ENVD_VERSION=0.1.1

cd ../orchestrator
ENVD_VERSION=0.1.1 ./k8s/envd/install.sh
```

然后把 API 和 worker 的 `ORCHESTRATOR__ENVD__VERSION` 改为 `0.1.1` 并滚动更新。
运行中的 Sandbox 已经启动的 envd 进程不会被替换；暂停再恢复或重建 Pod 后会使用节点上的
新版本。版本标签在升级期间被临时移除，因此恢复操作只会短暂等待，不会启动到半更新节点。

## 故障处理

Sandbox 因节点标签缺失而 Pending：

```bash
kubectl get nodes -L litterbox.io/envd-version
kubectl -n litterbox describe daemonset envd-node-installer
kubectl -n litterbox get pods -l app.kubernetes.io/name=envd-node-installer
```

installer 失败时先查看 init container 日志：

```bash
POD=$(kubectl -n litterbox get pod -l app.kubernetes.io/name=envd-node-installer \
  -o jsonpath='{.items[0].metadata.name}')
kubectl -n litterbox logs "$POD" -c installer
```

修复并重新执行 `install.sh`。不要手工添加版本标签来绕过安装验证。

## 卸载

先关闭 orchestrator 注入，再删除调度标签和 DaemonSet：

```bash
kubectl label nodes -l katacontainers.io/kata-runtime=true \
  litterbox.io/envd-version-
kubectl -n litterbox delete daemonset envd-node-installer
```

确认没有 Sandbox 需要 envd 后，再在每个节点删除
`/opt/litterbox/bin/sandbox-agent`。删除节点文件会影响后续恢复或重建的 Sandbox。
