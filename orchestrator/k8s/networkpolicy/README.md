# Sandbox 网络隔离

Sandbox 与集群内其他工作负载默认处于同一个扁平网络：任意 Pod 都能连上任意 Pod。
这带来两个问题：

1. Sandbox 能直连内部的 Postgres、Redis 等数据服务。
2. `envd` sidecar（`sandbox-agent-go`）监听 `0.0.0.0:49983` 且**没有鉴权**，
   暴露了任意文件读写和进程启动接口。因此**谁能连上 49983，谁就能在对应 Sandbox
   里执行任意命令**。没有策略时，Sandbox A 可以 RCE Sandbox B，集群里任何其他
   Pod 也可以 RCE 任意 Sandbox。

这个目录用 NetworkPolicy 把可达性收敛成一份白名单。因为 sidecar 本身没有鉴权，
**可达性本身就是访问控制**。

## 组件

| 项目 | 路径或名称 |
| --- | --- |
| 策略模板 | `k8s/networkpolicy/sandbox-networkpolicy.yaml.tmpl` |
| 安装脚本 | `k8s/networkpolicy/install.sh` |
| 策略对象 | `<sandbox-namespace>/sandbox-ingress`、`<sandbox-namespace>/sandbox-egress` |
| 默认 Sandbox 命名空间 | `default` |
| 默认选择器 | `component=sandbox` |

## 策略语义

两条策略都作用在 Sandbox Pod 上，缺一不可。

**`sandbox-ingress`** —— 只允许两个来源连接 Sandbox：

| 来源 | 用途 |
| --- | --- |
| `litterbox` | orchestrator 的 envd 代理（直连 Pod IP 的 envd 端口） |
| `kube-system` | traefik，用于暴露端口的 Service |

其余一律拒绝，包括**同一个命名空间里的其他 Sandbox**（跨租户 RCE 的入口）以及
集群里任何其他 Pod。kubelet 探针不受影响：策略控制器始终放行源地址为本节点的流量
（`addrtype --src-type LOCAL`）。

**`sandbox-egress`** —— 只允许三类出向：

| 目标 | 用途 |
| --- | --- |
| `kube-system:53` UDP/TCP | 集群 DNS |
| `pai` 中带 `app=runlet-traefik-billing` 标签的 Pod 的 `8080` | 计费出口代理（`http_proxy`） |
| `0.0.0.0/0`，排除 `10.42.0.0/16` 与 `10.43.0.0/16` | 公网 |

排除 Pod 网段和服务网段就是切断 Sandbox 到内部服务（Postgres、Redis、控制面）的
路径，同时保留公网访问。

### 为什么按命名空间而不是按端口放行 ingress

orchestrator 的 envd 代理是**直连 Sandbox Pod IP** 的，而暴露端口走
traefik → Service → Pod。两者端口不同且暴露端口是动态的，按端口列举容易漏。按
命名空间放行可以同时覆盖两条路径。

### 为什么 egress 之外还要 ingress

只靠 egress 已经能挡住 Sandbox 互相访问——因为 `except` 排除了整个 Pod 网段。但那是
**单条策略的副作用**：一旦 `sandbox-egress` 被删除或放宽，跨租户 RCE 会立刻恢复，而且
挡不住「非 Sandbox 的 Pod → Sandbox」。ingress 策略是独立且有意为之的那把锁。

## 应用

```bash
cd orchestrator
./k8s/networkpolicy/install.sh
```

脚本是幂等的，重复执行会原地更新已存在的策略。可选参数：

```bash
./k8s/networkpolicy/install.sh --dry-run   # 只渲染并打印，不做任何变更
./k8s/networkpolicy/install.sh --verify    # 应用后跑一次真实生效性测试
./k8s/networkpolicy/install.sh --delete    # 删除两条策略
```

应用前脚本会校验：引用的命名空间都存在、`pai` 下确实有 Pod 匹配计费代理标签、以及
节点上是否存在 `KUBE-NWPLCY` 链（后者只告警）。命名空间或计费标签写错时策略会
「看上去应用成功但什么都没匹配到」，所以这几项是硬校验。

### 可配置项

| 变量 | 默认值 |
| --- | --- |
| `SANDBOX_NAMESPACE` | `default` |
| `SANDBOX_LABEL_KEY` / `SANDBOX_LABEL_VALUE` | `component` / `sandbox` |
| `ORCHESTRATOR_NAMESPACE` | `litterbox` |
| `INGRESS_NAMESPACE` | `kube-system` |
| `DNS_NAMESPACE` | `kube-system` |
| `BILLING_NAMESPACE` | `pai` |
| `BILLING_LABEL_KEY` / `BILLING_LABEL_VALUE` | `app` / `runlet-traefik-billing` |
| `BILLING_PORT` | `8080` |
| `CLUSTER_POD_CIDR` | `10.42.0.0/16` |
| `CLUSTER_SERVICE_CIDR` | `10.43.0.0/16` |

## 验证

```bash
./k8s/networkpolicy/install.sh --verify
```

脚本会创建两个带 Sandbox 标签的探针 Pod，因此测的是线上真实策略而不是副本，最后
无论成败都会清理。预期结果：

| 检查项 | 期望 |
| --- | --- |
| Sandbox → Sandbox | BLOCKED |
| Sandbox → 计费代理 | OPEN |
| Sandbox → 公网 | OPEN |
| Sandbox → orchestrator Postgres | BLOCKED |

手工验证单个 Sandbox：

```bash
SBX=<sandbox-id>
# 出向：内部服务应超时，公网应连通
kubectl -n default exec "$SBX" -- python3 -c \
  "import socket;s=socket.socket();s.settimeout(5);s.connect(('postgres.litterbox.svc.cluster.local',5432))"
# 入向：orchestrator 仍应能连上 sidecar
kubectl -n litterbox exec deploy/orchestrator-service -- \
  python3 -c "import socket;s=socket.socket();s.settimeout(5);s.connect(('<sandbox-pod-ip>',49983))"
```

**注意策略生效有延迟。** k3s 的策略控制器（kube-router）按周期同步 ipset。**刚创建
的 Pod 立刻测试会被误判为 BLOCKED**，因为它的 IP 还没进入 allow 集合。新建 Pod 后
至少等待 20–30 秒再测试，`--verify` 里的 `IPSET_SETTLE_SECONDS`（默认 30）就是为此。

## 故障处理

Sandbox 建好后就连不上内部服务，先确认策略是否选中了它：

```bash
kubectl -n default get networkpolicy sandbox-ingress sandbox-egress
kubectl -n default get pods -l component=sandbox --show-labels
```

Sandbox 能否被 orchestrator 访问（envd 路径断了会导致控制台功能异常）：

```bash
kubectl -n litterbox logs deploy/orchestrator-service --tail=50
```

计费代理被误伤时，确认标签仍然匹配：

```bash
kubectl -n pai get pods -l app=runlet-traefik-billing
```

策略没有生效时，确认策略控制器没有被关掉（k3s 的 `--disable-network-policy` 会静默
禁用全部 NetworkPolicy）：

```bash
iptables-save | grep -c KUBE-NWPLCY
```

## 卸载

```bash
./k8s/networkpolicy/install.sh --delete
```

删除后 Sandbox 立刻恢复与集群的完全互通——包括 Sandbox 之间。仅在确认不再需要隔离
时执行。

## 已知边界

- 计费代理的可绕过性不在这里处理。`http_proxy` 只对主动尊重该环境变量的程序生效，
  用原始 socket 或非 HTTP 协议可以直接绕过计量。NetworkPolicy 不做七层识别。
- `RUNLET_SKILL_TOKEN` 这类注入到 Sandbox 的凭据不在这里处理。白名单目前**只放行
  计费代理**；如果将来 Sandbox 需要访问 `runlet-skill-server` 等内部服务，必须把对应
  的命名空间/标签/端口加进 egress 模板，否则会连接超时。
