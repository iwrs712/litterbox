// Sandbox 沙盒编排系统类型定义

// Sandbox 状态
export type SandboxStatus = 'created' | 'running' | 'stopped' | 'exited' | 'unknown' | 'pooled' | 'creating';

// Sandbox 池状态
export type PoolState = 'none' | 'creating' | 'available' | 'allocated' | 'failed';

// Host Path Mount 主机路径挂载
export interface HostPathMount {
  host_path: string; // 主机路径
  container_path: string; // 容器内路径
  read_only: boolean; // 是否只读
}

export interface LifecycleExecAction {
  command: string[];
}

export interface LifecycleAction {
  exec: LifecycleExecAction;
}

export interface PreStopLifecycleAction extends LifecycleAction {
  terminationGracePeriodSeconds?: number;
}

export interface TemplateLifecycle {
  postStart?: LifecycleAction;
  preStop?: PreStopLifecycleAction;
}

// Sandbox 主体
export interface Sandbox {
  id: string;
  name: string;
  template_id: string;
  image: string;
  cpu_millicores: number;
  memory_mb: number;
  status: SandboxStatus;
  pool_state: PoolState;
  allocated_at?: string;
  metadata?: Record<string, any>;
  created_at: string;
  updated_at: string;
  ttl_seconds?: number;
  expires_at?: string;
  time_remaining_seconds?: number;
}

// Template 定义 - 模板是全局资源，不属于特定租户
export interface Template {
  id: string;
  name: string;
  description?: string;
  image: string;
  command?: string; // 容器启动命令（字符串），可选
  env?: string[]; // 环境变量数组，格式为 "KEY=VALUE"
  host_path_mounts?: HostPathMount[]; // 主机路径挂载列表
  cpu_millicores: number; // 1000m = 1核
  cpu_request?: number; // 毫核
  memory_mb: number;
  memory_request?: number;
  ttl_seconds?: number; // TTL 秒数，可选，范围 300-86400（5分钟-24小时）
  lifecycle?: TemplateLifecycle;
  metadata?: Record<string, any>; // 包含 user_id 等自定义字段
  created_at: string;
  updated_at: string;
}

// 创建 Sandbox 请求
export interface CreateSandboxRequest {
  name: string;
  template_id: string;
  metadata?: Record<string, any>;
}

// 创建 Template 请求 - 模板是全局资源，不需要 tenant_id
export interface CreateTemplateRequest {
  id?: string; // 可选，不传则自动生成
  name: string;
  description?: string;
  image: string;
  command?: string; // 容器启动命令（字符串），可选
  env?: string[]; // 环境变量数组，格式为 "KEY=VALUE"
  host_path_mounts?: HostPathMount[]; // 主机路径挂载列表
  cpu_millicores: number; // 1000m = 1核
  cpu_request?: number; // 毫核
  memory_mb: number;
  memory_request?: number;
  ttl_seconds?: number; // TTL 秒数，可选，范围 300-86400（5分钟-24小时）
  lifecycle?: TemplateLifecycle;
  metadata?: Record<string, any>; // 包含 user_id 等自定义字段
}

// 更新 Template 请求
export interface UpdateTemplateRequest {
  name?: string;
  description?: string;
  image?: string;
  command?: string; // 容器启动命令（字符串），可选
  env?: string[]; // 环境变量数组，格式为 "KEY=VALUE"
  host_path_mounts?: HostPathMount[]; // 主机路径挂载列表
  cpu_millicores?: number; // 1000m = 1核
  cpu_request?: number; // 毫核
  memory_mb?: number;
  memory_request?: number;
  ttl_seconds?: number; // TTL 秒数，可选，范围 300-86400（5分钟-24小时）
  lifecycle?: TemplateLifecycle;
  metadata?: Record<string, any>; // 包含 user_id 等自定义字段
}

// 池配置和状态 - 池是全局资源，不属于特定租户
export interface PoolStatus {
  template_id: string;
  enabled: boolean;
  min_ready: number;        // low-water trigger threshold
  target_ready: number;     // fill target (how many to keep ready)
  max_creating: number;     // max concurrent creating sandboxes
  ready: number;            // currently ready sandboxes
  creating: number;         // currently creating sandboxes
  allocated: number;        // currently allocated sandboxes
  failed: number;           // currently failed sandboxes
  terminating: number;      // currently terminating sandboxes
}

// 创建池请求
export interface CreatePoolRequest {
  min_ready: number;         // required, 1-50
  target_ready?: number;     // optional, 1-100, defaults to min_ready
  max_creating?: number;     // optional, 1-20, default 5
}

// 更新池请求
export interface UpdatePoolRequest {
  min_ready?: number;        // optional, 0-50 (set to 0 to disable)
  target_ready?: number;     // optional, 1-100
  max_creating?: number;     // optional, 1-20
}

// 命令执行
export interface ExecCommandRequest {
  command: string[];
  timeout?: number;
}

export interface ExecCommandResponse {
  exit_code: number;
  stdout: string;
  stderr: string;
  execution_time_ms: number;
}

// 列表响应（带分页）
export interface SandboxListResponse {
  sandboxes: Sandbox[];
  total: number;
  page: number;
  page_size: number;
}

export interface TemplateListResponse {
  templates: Template[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface PoolListResponse {
  pools: PoolStatus[];
  total: number;
}

// API 响应包装
export interface ApiResponse<T = unknown> {
  success: boolean;
  data?: T;
  error?: string;
}

// ==================== Service Expose ====================

// 服务暴露协议类型
export type ExposeProtocol = 'http' | 'tcp';

// 服务暴露状态
export type ExposeStatus = 'ready' | 'pending' | 'failed';

// 服务暴露实体
export interface ServiceExpose {
  id: string;
  sandbox_id: string;
  protocol: ExposeProtocol;
  internal_port: number;
  // HTTP 协议特有字段
  external_url?: string;
  domain?: string;
  path?: string;
  // TCP 协议特有字段
  external_ip?: string;
  external_port?: number;
  status: ExposeStatus;
  created_at: string;
}

// 创建服务暴露请求
export interface CreateServiceExposeRequest {
  protocol: ExposeProtocol;
  internal_port: number;
  path?: string; // 仅HTTP协议使用，默认 "/"
}

// ==================== Webhook ====================

// Webhook 事件类型
export type WebhookEvent = 'sandbox_started' | 'sandbox_ready' | 'sandbox_deleted';

// Webhook 重试配置
export interface WebhookRetryConfig {
  max_attempts: number; // 最大重试次数，默认 5
  interval_ms: number; // 重试间隔（毫秒），默认 200
  timeout_ms: number; // 超时时间（毫秒），默认 1000
}

// Webhook 实体
export interface Webhook {
  id: string;
  name: string;
  user_id: string;
  url: string;
  token: string;
  template_ids: string[];
  events: WebhookEvent[];
  retry: WebhookRetryConfig;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

// 创建 Webhook 请求
export interface CreateWebhookRequest {
  name: string;
  user_id: string;
  url: string;
  token: string;
  template_ids: string[];
  events: WebhookEvent[];
  retry?: WebhookRetryConfig;
  enabled?: boolean;
}

// 更新 Webhook 请求
export interface UpdateWebhookRequest {
  name?: string;
  url?: string;
  token?: string;
  template_ids?: string[];
  events?: WebhookEvent[];
  retry?: WebhookRetryConfig;
  enabled?: boolean;
}

// Webhook 列表响应
export interface WebhookListResponse {
  webhooks: Webhook[];
  total: number;
}

// ── Metrics（沙盒创建指标）─────────────────────────────────────

// 每分钟一个 bucket，共 60 个（最近 1h）
export interface MetricsTimelineBucket {
  minute_ago: number;
  count: number;
  success: number;
  fail: number;
  source_pool: number;
  source_direct: number;
  p50: number | null;
  p90: number | null;
}

export interface MetricsLive {
  total: number;
  running: number;
  stopped: number;
  creating: number;
}

export interface MetricsTemplateStats {
  total: number;
  success: number;
  fail: number;
  success_rate: number | null;
  p50: number | null;
  p90: number | null;
}

// /api/v1/metrics/snapshot 响应体
export interface MetricsSnapshot {
  window_seconds: number;
  total: number;
  success: number;
  fail: number;
  success_rate: number | null;
  p50_seconds: number | null;
  p90_seconds: number | null;
  live: MetricsLive | null;
  by_template: Record<string, MetricsTemplateStats>;
  timeline: MetricsTimelineBucket[];
}
