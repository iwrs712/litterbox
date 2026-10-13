# AgentENV 与 Litterbox Orchestrator 功能调研

> 调研日期：2026-08-09  
> AgentENV 代码基线：`f24720d6b074482844f14a9a0bc7e041dbc89188`  
> AgentENV 文档基线：`https://kvcache-ai.github.io/AgentENV/dev/`  
> 当前项目：`litterbox/orchestrator`，同时检查了相邻的 Dashboard 源码  
> 本文以源码和公开文档为证据；性能数字是 AgentENV 的项目主张，未经本次调研独立压测。

## 1. 执行结论

AgentENV 和当前项目是相邻但不同层次的系统：

- **AgentENV** 是完整的 Firecracker microVM runtime。它自行实现虚拟机、块设备、快照、暂停/恢复、模板构建、网络代理和多节点调度。
- **Litterbox Orchestrator** 是 Kubernetes sandbox control plane。它管理 Template、Sandbox、Deployment、PVC、Service/Ingress、TTL、warm pool、Webhook、Dashboard 和 workspace 文件接口；隔离 runtime 由 Kubernetes RuntimeClass 决定。

如果目标是“闲置时释放 CPU/内存，恢复时继续原进程、内存和根文件系统状态”，AgentENV 明显更接近需求。它的 pause 会持久化 Firecracker memory snapshot 与磁盘增量，resume 从该状态重建同一个 sandbox。

如果目标是“继续基于 k3s/Kubernetes，并给 `/workspace` 一个可配置、可扩容、有真实容量边界的独立数据卷”，当前项目的 PVC 方案更直接。当前项目的 suspend 是 Deployment 缩容到 0：文件保留在 PVC，但进程、内存、网络连接和 rootfs writable layer 不保留。

**不要把 AgentENV 看作给现有 Deployment 换一个 `runtimeClassName`。** AgentENV 需要 `/dev/kvm`、kernel 6.8+、特权网络、ublk/overlaybd、自己的 snapshot repository 和 gateway/scheduler。现有 Deployment/PVC 生命周期不能直接驱动其完整 Firecracker pause/resume。

### 最关键的判断

1. AgentENV 能提供更明确的 guest rootfs 块设备边界，以及 rootfs/attached drive 的 `diskSizeMB`。
2. `diskSizeMB` 是 guest 可见的虚拟块设备容量，不等价于每个租户自动获得 Kubernetes PVC 或预分配同等大小的宿主机物理空间。
3. 现有 workspace PVC 已经解决了 `/workspace` 的真实容量边界和 StorageClass 扩容；它没有解决 rootfs、镜像缓存、日志等对宿主机磁盘的占用。
4. AgentENV 的 pause 不等于永久备份。永久 delete 后要恢复，必须先创建 committed snapshot，或单独保留数据 artifact。
5. 当前项目的业务能力，尤其 Dashboard、Template 配置、workspace policy、TTL、lock、expose、webhook 和 warm pool，不会被 AgentENV 自动替代。
6. 推荐路线：**当前 Kubernetes + PVC 继续作为默认 runtime；AgentENV 先作为独立 Firecracker backend PoC，再决定是否接入。**

## 2. 调研范围与证据

### 2.1 AgentENV

本地代码目录：`/Users/v_chenyongjie01/personal_project/github/litterbox/AgentENV-main`。

已在该目录初始化 CodeGraph：479 个文件、13,728 个节点、58,118 条边。重点检查的模块如下：

| 主题 | 源码位置 |
|---|---|
| Sandbox 生命周期 | `src/orchestrator/service.rs` |
| Paused state 持久化 | `src/orchestrator/persistence/file_backed.rs` |
| Firecracker runtime | `src/sandbox/firecracker/sandbox.rs` |
| Firecracker drive attach | `src/sandbox/firecracker/instance.rs` |
| Extra drive | `src/sandbox/extra_drive.rs` |
| Attached-drive API | `src/api/impls/attached_drives.rs` |
| HTTP API | `src/api/impls/sandbox.rs`、`src/api/openapi.yml` |
| Snapshot repository | `src/snapshot/repository/`、`src/snapshot/manager.rs` |
| Scheduler/Gateway | `services/scheduler/`、`services/gateway/` |
| 配置和文档 | `config/default.toml`、`docs/src/` |

### 2.2 当前项目

| 主题 | 源码位置 |
|---|---|
| 总体架构 | `ARCHITECTURE.md` |
| Sandbox 生命周期和 PVC | `src/orchestrator/services/sandboxes.py` |
| Pool | `src/orchestrator/services/pools.py` |
| Kubernetes Gateway | `src/orchestrator/infra/kubernetes.py` |
| API schema | `src/orchestrator/domain/models.py` |
| Sandbox API | `src/orchestrator/routes/sandboxes.py` |
| workspace exec/files | `src/orchestrator/services/workspace.py` |
| 配置 | `src/orchestrator/config.py`、`config.toml` |
| LVM StorageClass | `k8s/storage/` |

## 3. AgentENV 架构与运行模型

### 3.1 单节点架构

一个 AgentENV sandbox 是一个 Firecracker microVM，拥有独立 Linux kernel、rootfs、network namespace、进程和内存状态。核心流如下：

```text
HTTP / E2B SDK / aenv CLI
        |
        v
AgentENV API (Rust/Axum)
        |
        v
Orchestrator
  |        |           |
  v        v           v
Firecracker  overlaybd + ublk  snapshot repository
  |
  v
envd in guest: command, file, process, health
```

`envd` 是 VM 内的 daemon，执行命令、文件操作和进程管理。外部 HTTP、SSE、WebSocket 请求可通过 AgentENV reverse proxy 访问 VM 内服务。

### 3.2 存储模型

AgentENV 的 rootfs 使用 layered block device：基础 OCI/image layers 只读共享，每个 sandbox 有 writable upper。overlaybd 提供分层块映像，ublk 把用户态块设备交给 Firecracker 作为 drive。

```text
base image layers (read-only, shareable)
             +
sandbox writable upper
             |
             v
overlaybd virtual block device -> ublk -> Firecracker drive -> guest rootfs
```

这个模型的价值是：guest 不直接获得宿主机根文件系统的真实可见空间，而是只看到分配给 VM 的块设备视图。代价是 image cache、upper、memory snapshot、snapshot repository 和日志仍要落在宿主机或远端存储上，需要独立容量治理。

### 3.3 多节点架构

多节点部署不把 sandbox 变成 Kubernetes Pod。Kubernetes 只用于部署 AgentENV 自己的服务：

| 工作负载 | 类型 | 作用 |
|---|---|---|
| `agentenv-node` | privileged DaemonSet | 每节点一个 Firecracker runtime，访问 `/dev/kvm`、host network 能力和本地 `/var/lib/aenv` |
| `agentenv-gateway` | Deployment | 按 sandbox ID 转发 HTTP/data plane 请求 |
| `agentenv-scheduler` | 单副本 Deployment | 节点选择、sandbox-to-node binding、心跳、P2P peer 发现 |
| `agentenv-nodes` | Headless Service | Scheduler 的 EndpointSlice 发现 |

Scheduler 的 `Schedule` 会读取 ready nodes、按资源阈值过滤、再按策略选节点。当前文档明确说明 sandbox binding 为内存态，scheduler 应保持单副本，重启后 binding 会丢失。这是生产 HA 的显著缺口。

### 3.4 宿主机前置条件

官方文档要求 Linux kernel 6.8+ 和 `/dev/kvm`。Kubernetes 版要求 runtime DaemonSet privileged，访问 host KVM、网络 namespace/iptables 和 host-local 数据路径。若嵌套虚拟化不可用，文档提供实验性 PVM，但仍要求替换 host kernel、加载 PVM module，并使用配套 guest/runtime artifacts。

现有 k3s + Kata 环境不能自动满足以上条件。必须独立验证 KVM、`ublk_drv`、Firecracker、overlaybd、网络能力和 CNI/iptables 兼容性。

## 4. AgentENV 的关键功能

### 4.1 Template 是 committed snapshot 的用户界面

AgentENV Template 的实质是可启动 snapshot：从 OCI image 或 Dockerfile 创建临时 sandbox，执行构建步骤，再将最终状态发布为 committed snapshot；Template ID/alias 指向该 snapshot。新 sandbox 从 snapshot 启动。

这和当前项目不同：当前 Template 是 ConfigMap 中的 image、command、env、资源、workspace、TTL 等配置，Sandbox 创建时通过 Kubernetes Deployment 拉镜像启动；模板本身不含运行时 memory/rootfs snapshot。

### 4.2 rootfs `diskSizeMB`

Cold sandbox API 支持 `diskSizeMB`：

- 设置新建 writable rootfs 的虚拟容量。
- 最小 1024 MiB，粒度为 1024 MiB。
- 默认允许增长；默认不允许 shrink。
- 只应用于 fresh writable rootfs，不会在 snapshot resume 时任意改变既有快照的尺寸。
- API response 会返回 `diskSizeMB`。

这是 guest-visible rootfs 容量边界，但不是一个自动 preallocate 的 per-sandbox physical quota。默认 `image.cache.capacity_gb` 是节点级 cache 容量，snapshot repository 需要单独设置保留、容量和 GC 策略。

### 4.3 Attached drives

`attachedDrives` API 的每个 drive 允许配置：

- `driveID`：唯一 drive 名称。
- `source.image`：由 image resolver 解析为 overlaybd source。
- `readOnly`：默认只读。
- `mountPath`：guest 内路径，默认 `/mnt/<driveID>`。
- `subPath`：drive 内相对路径。
- `diskSizeMB`：cold launch 的虚拟 drive 容量。

`resolve_attached_drives` 会校验 drive ID/mount path/subPath/容量，转换为 `ExtraDrive::Overlaybd`。Firecracker 通过 `add_drive` 将它作为独立磁盘附加到 VM。暂停/快照时，extra drive 的 writable layer 会被捕获。

这比普通容器挂载更接近“真正的 guest block device”，但它不是 Kubernetes PVC：

1. 数据持久性来自 AgentENV snapshot/image repository。
2. `diskSizeMB` 是虚拟容量，不是 CSI/LVM 的独立物理卷对象。
3. 当前 attached-drive 模型来源是 image/overlaybd snapshot；并没有发现一个可直接 attach 任意 Kubernetes PVC 的通用 API。

### 4.4 pause/resume 的真正语义

TTL 到期时 AgentENV 默认 auto-pause；创建时设置 `autoPause: false` 才选择 delete。显式 API/CLI 包含 pause、resume 和 timeout。

`pause_sandbox_inner` 的实际步骤是：

1. `Running -> Pausing` 的 compare-and-set 状态转换。
2. pin 住 paused runtime 使用的 image refs，防止 cache GC。
3. 分配 persistent artifact root。
4. 将运行 handle 和 proxy route detach。
5. 调用 backend pause，保存 Firecracker VM state、memory、rootfs upper、attached-drive upper 和 manifest。
6. `FileBackedSandboxPersister::persist_paused` 写入 paused record。
7. 发布 `Paused` 状态。

默认本地持久化路径是：

| 路径 | 内容 |
|---|---|
| `$AENV_HOME/persisted-sandboxes/records.db` | lifecycle、sandbox metadata、artifact root、paused state |
| `$AENV_HOME/persisted-sandboxes/artifacts/<sandbox>/<generation>/` | Firecracker manifest、VM state、rootfs/memory/drive artifacts |
| `$AENV_HOME/snapshot-store/` | committed snapshots/templates，或使用配置的 POSIX/OSS backend |
| `$AENV_HOME/image-cache/` | OCI/overlaybd node-local image cache |

恢复时 `resume_sandbox_inner` 校验 virtualization mode，先把记录标为 `Resuming`，从 paused state 创建 runtime。恢复失败会回滚为 Paused；服务重启时遗留的 `Resuming` 记录会被清理。

### 4.5 snapshot、fork 和 delete

必须区分三个操作：

| 操作 | 数据语义 |
|---|---|
| `pause` | 保存当前 sandbox 的完整暂停状态，后续 resume 同一 sandbox ID |
| `snapshot create` | 创建独立 committed snapshot，可作为 template 或新 sandbox/fork 来源 |
| `delete/kill` | 删除 sandbox runtime；不能假设未提交的 paused state 仍能作为永久备份 |

AgentENV 可以从 running sandbox 创建 snapshot，随后源 sandbox 继续运行；也可以 fork 为多个 child。对于“删除后还要恢复用户数据”，应先创建 committed snapshot，或将 workspace 设计为独立可保留 artifact，不能直接依赖 delete 后还存在暂停状态。

### 4.6 网络、代理和 E2B 生态

AgentENV 提供 per-sandbox network namespace、`allowInternetAccess`、`allowOut`/`denyOut` egress 策略、HTTP/SSE/WebSocket proxy。代理支持 `x-agentenv-sandbox-id`/`x-agentenv-target-port`，也接受 E2B 兼容头 `e2b-sandbox-id`/`e2b-sandbox-port`。

它还提供 `aenv` CLI 和 E2B-compatible API，已有 E2B Python/TypeScript SDK 的客户端可直接指向 AgentENV URL。当前项目则是自己的 `/api/v1` schema，不可无适配地替换。

### 4.7 安全限制

AgentENV README 明确警告当前没有适合公网暴露的 authorization。源码 `src/api/impls/auth.rs` 的 TODO 说明：当前只检查 `X-API-Key`、`X-Team-ID`、`X-Admin-Token` 或 Basic/Bearer header 是否非空，并不校验配置的 credential，也没有租户授权模型。

因此即使 API 叫作 E2B API key，也不能在生产中把它当成安全边界。部署时需要 API gateway、真正的 token 校验、租户权限、rate limit 和审计。

## 5. 当前 Litterbox Orchestrator 的能力

### 5.1 运行和控制面

当前项目是 FastAPI + Celery + Redis + Kubernetes Python SDK：

```text
Dashboard / Client
        |
        v
FastAPI
  |       |       |
  v       v       v
SandboxService  PoolService  WorkspaceService
        |
        v
Kubernetes Deployment / Pod / PVC / Service / Ingress
```

Template、Pool、Webhook 用 ConfigMap 存储；Sandbox 的业务 metadata 用 Deployment labels/annotations 存储；Redis 提供 TTL queue、pool locks 与 Celery transport。

默认 runtime class 是 `kata-clh`。它是 Kubernetes RuntimeClass 选择，不是 AgentENV/Firecracker runtime 集成。

### 5.2 workspace PVC

当前 Sandbox 创建过程：

```text
Create Sandbox
  -> 解析 global < template < sandbox workspace policy
  -> create workspace-<sandbox-id> PVC
  -> create Deployment
  -> mount PVC at effective mount_path
  -> wait Pod Ready
```

workspace policy 字段为 `enabled`、`mount_path`、`size`、`storage_class`。最终 resolved policy 写入 `litterbox.io/workspace-config` annotation，API response 和 Dashboard 显示 effective policy。

当前推荐 StorageClass 为 `litterbox-workspace-lvm`，后端是 OpenEBS LocalPV-LVM；配置为 `WaitForFirstConsumer`、`allowVolumeExpansion`，永久删除 Sandbox 后由于 `reclaimPolicy=Delete` 释放 backing LV。PVC `1Gi` 是真实的 guest-visible filesystem/block capacity，而不是宿主机根目录显示空间的软约束。

### 5.3 当前生命周期语义

| 操作 | Deployment/Pod | PVC | 进程内存 |
|---|---|---|---|
| `DELETE /api/v1/sandboxes/{id}` | 删除 Deployment、expose | 删除 | 永久丢失 |
| `POST /{id}/suspend` | replicas 缩到 0，Pod 结束 | 保留 | 丢失 |
| `POST /{id}/resume` | replicas 恢复为 1，新 Pod 启动 | 复用 | 从头启动 |
| TTL 到期 | 调用 suspend | 保留 | 丢失 |
| `ttl_seconds=0` | 不进入过期调度 | 不影响 | 不超时 |

这正是当前方案的价值与边界：可释放 Pod 资源且保留 `/workspace`，但并不是 VM checkpoint。

### 5.4 当前项目额外具备的业务功能

- Template CRUD，包含 image、command、env、CPU/memory、host mount、workspace、TTL、lifecycle、metadata。
- Sandbox 创建时 env/workspace override。
- warm pool 和 Redis 并发锁。
- HTTP Service + Ingress、TCP NodePort expose。
- Webhook 订阅、Celery retry。
- 文件/exec、terminal、ACP WebSocket。
- Dashboard 的 template/sandbox/workspace、暂停/恢复、lock/unlock 操作。
- Prometheus 和 JSON metrics snapshot。

AgentENV 没有直接替代这些业务控制面能力；反之，当前项目没有 Firecracker full snapshot、fork、attached drive API、per-sandbox network policy 和 AgentENV gateway/scheduler。

## 6. 功能矩阵

| 维度 | AgentENV | 当前项目 | 判断 |
|---|---|---|---|
| 隔离单位 | Firecracker microVM，独立 kernel/rootfs/network | Kubernetes Pod，当前 Kata RuntimeClass | AgentENV 隔离边界更清晰；当前 K8s 集成更直接 |
| Rootfs | overlaybd/ublk virtual block device | containerd/Kata container rootfs | AgentENV 更适合 rootfs 容量和视图隔离 |
| Rootfs 配额 | `diskSizeMB` guest-visible 虚拟容量 | 应用层尚无 rootfs size 字段 | AgentENV 领先，但仍要治理 backing storage |
| Workspace | attached drive / rootfs snapshot | per-Sandbox PVC，路径/大小/SC 可配置 | 当前独立 workspace 生命周期更成熟 |
| Workspace 容量 | drive `diskSizeMB`，非 PVC 对象 | PVC request + LVM CSI 真实容量边界 | 两者都能限制 guest；物理后端完全不同 |
| Pause | memory + disk + drives snapshot | scale Deployment to 0 | 语义根本不同 |
| Resume | 恢复 VM runtime 和同一 sandbox ID | 重新创建 Pod，复用 PVC | 只有 AgentENV 能保留进程态 |
| TTL | 默认 pause，`autoPause=false` 可 delete | 到期 suspend；0 表示无超时 | 当前 TTL 已符合“保文件、回收运行资源” |
| Delete 后恢复 | 需预先 committed snapshot | 当前 delete 删除 PVC，不能恢复 | 两者都要显式备份策略 |
| Snapshot/Fork | 原生 | 无 | AgentENV 适合 agent 分叉任务 |
| Template | committed snapshot + alias | 配置型 Template | 模型不同，不能直接字段映射 |
| 多节点 | Gateway + Scheduler + runtime DaemonSet | K8s scheduler/Deployment controller | AgentENV 自带 data plane，但 scheduler 现有 HA 弱 |
| 网络 | namespace、egress policy、proxy | Service/Ingress/NodePort | AgentENV 更细；当前更 K8s-native |
| Authentication | 仅 header non-empty，非生产授权 | bearer token，仍需网关/RBAC | AgentENV 必须额外加安全边界 |
| API | E2B-compatible | 自定义 `/api/v1` | 需要 adapter |
| 运维难度 | KVM + ublk + overlaybd + snapshots + gateway/scheduler | k3s + Kata + CSI + orchestrator | AgentENV 获得能力的同时引入较大运维面 |
| Dashboard | CLI/API 为主 | 已有业务 Dashboard | 当前项目更适合作为产品控制台 |

## 7. 配额、workspace、备份的精确区别

需要分开讨论三层问题。

### 7.1 guest 可见容量

- AgentENV rootfs/attached drive：通过 `diskSizeMB` 形成虚拟块设备容量边界。
- 当前 workspace：PVC 的请求容量经 CSI/LVM 格式化并挂载，guest 看到该 filesystem 容量。

两者都能让用户写满后遇到空间上限，但 AgentENV 是 virtual block image 模型，当前项目是 PVC/CSI 模型。

### 7.2 宿主机实际占用

- AgentENV：upper、memory snapshots、attached-drive snapshots、node image cache、remote block cache、snapshot repository、logs 都占用 host/remote space。`image.cache.capacity_gb` 只是 node cache 保护，不是 per-sandbox 物理配额。
- 当前项目：workspace PVC 的 LVM LV 是独立容量边界；容器 rootfs、image cache、container logs 仍不受 workspace PVC 限制。

所以“给 `/workspace` 配额”不等于“保护整个宿主机”。若要防止恶意 sandbox 抢宿主磁盘，必须分别管 rootfs、workspace、image cache、snapshot store、logs 和 temporary artifacts。

### 7.3 永久性与备份

| 场景 | AgentENV | 当前项目 |
|---|---|---|
| pause 后保留 workspace | 保存 rootfs/drive snapshot | PVC 保留 |
| pause 后保留运行进程 | 支持 | 不支持 |
| delete 后恢复 | 先 snapshot/保留 artifact | delete 当前会删除 PVC |
| workspace 单独备份 | 需要定义 drive/rootfs artifact 导出语义 | 可使用 CSI VolumeSnapshot、卷备份或文件归档；业务 API 尚未实现 |
| 跨节点恢复 | OSS/shared snapshot repository | LocalPV 受节点拓扑限制，需要共享存储或备份恢复 |

### 7.4 扩容

AgentENV 的 virtual resize 与 fresh/snapshot resume 阶段有关，现有快照不能任意在恢复时修改磁盘尺寸。当前 PVC 可遵循较标准的路径：扩 backing device/VG，扩 PVC request，CSI 扩 LV，重新挂载时扩 filesystem。当前 LVM/PVC 方案在“后续加盘、VG 扩容、用户 workspace 扩容”上更符合 Kubernetes 运维习惯。

## 8. 对当前产品语义的影响

### 8.1 暂停不是同一个词

当前项目 suspend：

```text
Deployment 1 -> 0
Pod/进程结束
PVC 和文件保留
resume 创建新 Pod
```

AgentENV pause：

```text
Firecracker VM pause
memory/rootfs/drive snapshot
记录 paused state
resume 恢复原 VM runtime
```

统一产品 API 时必须显式暴露 `pause_mode=scale_to_zero|vm_snapshot`，或在 UI 中明确标注。不能把两者都宣传为“恢复原 sandbox”。

### 8.2 删除必须保持永久删除语义

当前 delete 会删除 Deployment、expose 和 PVC。AgentENV delete 会删除 runtime sandbox，但 committed snapshot 是独立资源。建议保持当前业务约定：`delete` 永久删除；“未来可恢复”必须是显式的 archive/snapshot 操作，而不是 delete 的隐藏副作用。

### 8.3 lock 是上层业务状态

当前 `locked` 表示 sandbox 不能 resume，但 TTL 仍可把它缩到 0。AgentENV 没有同名业务锁。若接入 AgentENV，lock 必须继续由 Litterbox control plane 存储，并在 Provider 的 resume 前拒绝调用 AgentENV API。

## 9. 建议的路线

### 9.1 不建议的方案

- 只把 Deployment `runtimeClassName` 改成 `firecracker`。
- 只替换 Kata runtime handler 而不实现 snapshot repository、memory restore、network 和 storage lifecycle。
- 认为 AgentENV attached drive 能直接替代 PVC。
- 把 delete 当成数据备份。

### 9.2 推荐的 Provider 边界

若后续接入 AgentENV，应引入 runtime adapter，而不是在 `SandboxService` 堆 runtime 分支：

```text
Litterbox control plane
  - business ID, metadata, TTL, lock, webhook, Dashboard
  - Template/workspace policy
          |
          v
RuntimeProvider
  - create / pause / resume / delete
  - exec / files / proxy
  - snapshot / fork (optional)
          |
          +-- KubernetesProvider: Deployment + PVC
          +-- AgentENVProvider: Firecracker + snapshot
```

应显式保存：`runtime_type`、`runtime_id`、`workspace_mode`、`workspace_ref`、`pause_mode`、`delete_policy` 和 snapshot reference。当前 Kubernetes sandbox 的 Deployment 名称与 AgentENV sandbox ID 都不能作为对方的替代物。

### 9.3 阶段 0：独立 AgentENV 验证

先不接 Dashboard，也不改当前 runtime，在专用节点做以下验证：

- `/dev/kvm`、kernel、ublk、overlaybd、privileged network 是否可用。
- cold rootfs `diskSizeMB` 的 guest `df` 和写满行为。
- attached drive 的 mount path、读写、写满行为和 `diskSizeMB`。
- 写文件和运行长进程后 pause/resume，验证文件、进程、环境变量、网络策略的真实恢复行为。
- `snapshot create` 后 delete 原 sandbox，再从 snapshot 启动新 sandbox。
- AgentENV 服务重启、节点重启、snapshot store 不可用、cache GC、空间耗尽时的恢复和失败语义。

### 9.4 阶段 1：继续加固当前 PVC 路线

这是当前最小风险路径：

- TTL 继续 suspend，保留 PVC。
- delete 保持永久删除，需长期保存时增加 archive/backup。
- 监控 PVC capacity/used、VG free、rootfs/cache/logs 使用量。
- 明确文档和 Dashboard：当前 workspace 有硬容量，但 rootfs 并未由同一 PVC 配额保护。
- 为 workspace 提供 CSI VolumeSnapshot、对象存储备份或文件级归档能力。

### 9.5 阶段 2/3：可选 AgentENV backend 和生产化

阶段 2：新增 `runtime_type=agentenv`，由 AgentENV template/snapshot 创建 sandbox；保持 Kubernetes runtime 原行为。`pause`、`resume`、`delete` 不可隐式映射，必须按 provider 语义执行。

阶段 3：在多节点生产化前，补齐真实认证授权、scheduler binding 持久化或明确单副本恢复策略、OSS/shared snapshot repository、cache/artifact/log 配额和 GC、KVM/PVM 兼容矩阵、灾备与容量耗尽演练。

## 10. 推荐结论

短期不建议整体迁移。当前 Kubernetes + PVC 方案继续承担默认 sandbox，尤其适合“保 `/workspace` 文件、支持 PVC 扩容、使用 Dashboard 运营”的业务。AgentENV 应作为可选的 Firecracker backend PoC，用来验证“完整 VM pause/resume、rootfs block boundary、snapshot/fork”这类当前方案无法提供的能力。

适合优先尝试 AgentENV 的 workload：长时间运行的 agent、需要恢复进程态的任务、需要 fork 中间状态的并行任务、对 rootfs/network 隔离要求更高的任务。

适合继续使用当前项目的 workload：主要只需持久化 `/workspace` 文件、依赖 Kubernetes PVC/CSI/Ingress/Namespace/RBAC、需要现有 Dashboard 和模板运营能力、希望减少底层 runtime 运维复杂度的任务。

## 11. 参考资料

### AgentENV 文档

- [Overview](https://kvcache-ai.github.io/AgentENV/dev/getting-started/overview.html)
- [How AgentENV Works](https://kvcache-ai.github.io/AgentENV/dev/concepts/overview.html)
- [Sandboxes](https://kvcache-ai.github.io/AgentENV/dev/concepts/sandboxes.html)
- [Snapshots](https://kvcache-ai.github.io/AgentENV/dev/concepts/snapshots.html)
- [Templates](https://kvcache-ai.github.io/AgentENV/dev/concepts/templates.html)
- [Kubernetes Deployment](https://kvcache-ai.github.io/AgentENV/dev/deployment/kubernetes.html)
- [Distributed Control Plane](https://kvcache-ai.github.io/AgentENV/dev/internals/services.html)
- [E2B Integration](https://kvcache-ai.github.io/AgentENV/dev/integration/e2b.html)
- [AgentENV GitHub](https://github.com/kvcache-ai/AgentENV/tree/main)

### AgentENV 源码证据

- `src/orchestrator/service.rs::pause_sandbox_inner`
- `src/orchestrator/service.rs::resume_sandbox_inner`
- `src/orchestrator/persistence/file_backed.rs::persist_paused`
- `src/orchestrator/persistence/file_backed.rs::load_all`
- `src/sandbox/firecracker/sandbox.rs::pause_to_dir`
- `src/sandbox/firecracker/instance.rs::add_drive`
- `src/api/impls/attached_drives.rs::resolve_attached_drives`
- `src/api/impls/auth.rs::extract_claims_from_header`
- `services/scheduler/internal/service.go::Schedule`

### 当前项目源码证据

- `src/orchestrator/services/sandboxes.py::create_sandbox`
- `src/orchestrator/services/sandboxes.py::suspend_sandbox`
- `src/orchestrator/services/sandboxes.py::resume_sandbox`
- `src/orchestrator/services/sandboxes.py::delete_sandbox`
- `src/orchestrator/services/sandboxes.py::_build_workspace_claim`
- `src/orchestrator/services/workspace.py::WorkspaceService`
- `src/orchestrator/domain/models.py::WorkspaceConfigOverride`
- `src/orchestrator/routes/sandboxes.py`
- `k8s/storage/README.md`
- `ARCHITECTURE.md`

## 12. 建议验收清单

### AgentENV

- [ ] rootfs 和 attached drive 的 guest-visible size 与 `diskSizeMB` 一致。
- [ ] 写满 drive 后只影响对应 drive，不突破 host/repository 保护阈值。
- [ ] pause/resume 后文件、进程、drive、网络策略符合产品承诺。
- [ ] 服务重启后 paused record 可恢复；失败恢复不会丢失可重试状态。
- [ ] delete 和 snapshot delete 的 artifact 清理边界可验证。
- [ ] API 前置真实认证、授权、租户隔离与审计。
- [ ] scheduler binding、snapshot repository 和 node-local cache 有 HA、容量和 GC 方案。

### 当前项目

- [ ] TTL 到期只 suspend，PVC 保留。
- [ ] `ttl_seconds=0` 不进入 TTL queue。
- [ ] permanent delete 有权限删除 Deployment、expose 和 PVC。
- [ ] Template workspace 与 Sandbox Custom workspace 覆盖优先级稳定。
- [ ] PVC 扩容后 guest filesystem 容量增长。
- [ ] Pod 被单独删除时不会误删 Sandbox Deployment 或 PVC。
