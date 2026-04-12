// VM 相关类型定义

export type VMStatus = 'created' | 'ready' | 'running' | 'paused' | 'stopped' | 'failed';

export interface VM {
  vm_id: string;
  template_id: string;
  slot_id: number;
  guest_ip: string;
  host_ip: string;
  mac: string;
  api_socket: string;
  overlay_path: string;
  status: VMStatus;
  pid: number;
  create_time: string;
  init_token?: string;
  agent_token?: string;
  metadata?: Record<string, any>;
  last_billing_time?: string;
}

export interface CreateVMRequest {
  template_id: string;
  metadata?: Record<string, string>;
}

// Template 相关类型定义

export interface Template {
  id: string;
  name: string;
  kernel: string;
  rootfs: string;
  vcpu_count: number;
  mem_size_mb: number;
  disk_size_mb: number;
  bandwidth_mbps: number;
  read_only: boolean;
  created_at: string;
  updated_at: string;
}

export interface CreateTemplateRequest {
  id: string;
  name: string;
  kernel: string;
  rootfs: string;
  vcpu_count: number;
  mem_size_mb: number;
  disk_size_mb: number;
  bandwidth_mbps: number;
  read_only?: boolean;
}

export interface UpdateTemplateRequest {
  name?: string;
  kernel?: string;
  rootfs?: string;
  vcpu_count?: number;
  mem_size_mb?: number;
  disk_size_mb?: number;
  bandwidth_mbps?: number;
  read_only?: boolean;
}

export interface TemplateListResponse {
  templates: Template[];
  count: number;
}

// Pool Configuration 相关类型定义

export interface PoolConfig {
  template_id: string;
  enabled: boolean;
  min_ready: number;        // low-water trigger threshold
  target_ready: number;     // fill target
  max_creating: number;     // max concurrent creating sandboxes
}

export interface UpdatePoolConfigRequest {
  min_ready?: number;
  target_ready?: number;
  max_creating?: number;
}

export interface PoolConfigListResponse {
  pools: PoolConfig[];
  count: number;
}

// Dashboard 池状态
export interface PoolStats {
  enabled: boolean;
  min_ready: number;
  target_ready: number;
  ready: number;
  template_id: string;
}

export interface TemplatePools {
  total_pools: number;
  pools: Record<string, PoolStats>;  // template_id -> stats
}

export interface DashboardOverview {
  timestamp: number;
  vms: {
    total: number;
    running: number;
    paused: number;
    stopped: number;
    failed: number;
  };
  resources: {
    template_pools: TemplatePools;
    system: {
      cpu_usage_percent: number;
      memory_used_mb: number;
      memory_total_mb: number;
      memory_usage_percent: number;
      disk_used_gb: number;
      disk_total_gb: number;
      disk_usage_percent: number;
    };
  };
}

export interface ApiError {
  error: string;
}

export interface ApiResponse<T = unknown> {
  data?: T;
  error?: string;
}

export type SnapshotStatus = 'creating' | 'partial' | 'completed' | 'failed';

export interface Snapshot {
  snapshot_id: string;
  vm_id: string;
  description?: string;
  create_time: string;
  status: SnapshotStatus;

  // File paths
  snapshot_path: string;
  memory_path: string;
  overlay_path: string;

  // Size information (bytes)
  snapshot_size: number;
  memory_size: number;
  overlay_size: number;
  total_size: number;

  // Timing
  mem_snap_completed_at?: string;
  overlay_completed_at?: string;

  // Error handling
  error_message?: string;
}

export interface CreateSnapshotRequest {
  description?: string;
}

export interface Route {
  vm_id: string;
  port: number;
  type: "http" | "tcp" | "udp";
  domain?: string;
  url?: string;
  protocol?: "tcp" | "udp";
  external_port?: number;
  external_ip?: string;
  access_info?: string;
}

export interface CreateRouteRequest {
  port: number;
  type: "http" | "tcp" | "udp";
  protocol?: "tcp" | "udp";
}

// Advanced Query Types
export interface VMQueryParams {
  status?: VMStatus[];
  include_idle?: boolean;
  created_after?: string;
  created_before?: string;
  limit?: number;
  offset?: number;
  sort_by?: 'create_time' | 'vm_id' | 'slot_id';
  sort_order?: 'asc' | 'desc';
}

export interface VMQueryResponse {
  vms: VM[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
  query_time: number;
}

export interface RouteQueryParams {
  vm_id?: string[];
  vm_status?: VMStatus[];
  port?: number;
  port_min?: number;
  port_max?: number;
  domain?: string;
  created_after?: string;
  created_before?: string;
  limit?: number;
  offset?: number;
  sort_by?: 'created_at' | 'vm_id' | 'port' | 'domain';
  sort_order?: 'asc' | 'desc';
}

export interface RouteQueryResponse {
  routes: Route[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
  query_time: number;
}

// Billing 相关类型定义

export interface BillingRecord {
  id: number;
  vm_id: string;
  template_id: string;
  start_time: string;
  end_time: string;
  duration_seconds: number;
  vcpu_count: number;
  mem_size_mb: number;
  disk_size_mb: number;
  status: VMStatus;
  status_coeff: number;
  cpu_cost: number;
  mem_cost: number;
  disk_cost: number;
  total_cost: number;
  created_at: string;
}

export interface VMBillingResponse {
  vm_id: string;
  template_id: string;
  period: {
    start_time: string;
    end_time: string;
    total_seconds: number;
  };
  resource_config: {
    vcpu_count: number;
    mem_size_gb: number;
    disk_size_gb: number;
  };
  cost_summary: {
    cpu_cost: number;
    mem_cost: number;
    disk_cost: number;
    total_cost: number;
  };
  records: BillingRecord[];
}

export interface UserVMBilling {
  vm_id: string;
  template_id: string;
  total_seconds: number;
  total_cost: number;
}

export interface UserBillingResponse {
  user_id: string;
  period: {
    start_time: string;
    end_time: string;
    total_seconds: number;
  };
  summary: {
    total_vms: number;
    total_cost: number;
    cpu_cost: number;
    mem_cost: number;
    disk_cost: number;
  };
  vms: UserVMBilling[];
}

export interface BillingConfig {
  cpu_price_per_sec: number;
  mem_price_per_sec: number;
  disk_price_per_sec: number;
  currency: string;
  effective_from: string;
  cpu_price_per_hour: number;
  mem_price_per_hour: number;
  disk_price_per_hour: number;
}
