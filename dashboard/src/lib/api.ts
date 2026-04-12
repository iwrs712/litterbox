// Litterbox API 客户端 - Sandbox 编排系统

import type {
  Sandbox,
  SandboxListResponse,
  CreateSandboxRequest,
  Template,
  TemplateListResponse,
  CreateTemplateRequest,
  UpdateTemplateRequest,
  PoolStatus,
  PoolListResponse,
  CreatePoolRequest,
  UpdatePoolRequest,
  ExecCommandRequest,
  ExecCommandResponse,
  SandboxStatus,
  ServiceExpose,
  CreateServiceExposeRequest,
  Webhook,
  WebhookListResponse,
  CreateWebhookRequest,
  UpdateWebhookRequest,
  MetricsSnapshot,
} from '@/types/sandbox';

const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8080';
const API_PREFIX = '/api/v1';

class ApiClient {
  private baseURL: string;

  constructor(baseURL: string) {
    this.baseURL = baseURL;
  }

  private async request<T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<T> {
    const url = `${this.baseURL}${endpoint}`;
    const headers: HeadersInit = {
      'Content-Type': 'application/json',
      ...options.headers,
    };

    const response = await fetch(url, {
      ...options,
      headers,
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({
        error: `HTTP ${response.status}`
      }));
      throw new Error(error.error || error.message || `HTTP ${response.status}`);
    }

    if (response.status === 204) {
      return {} as T;
    }

    const json = await response.json();

    // 如果响应是包装格式 {success: true, data: {...}}，解包data
    if (json.success !== undefined && json.data !== undefined) {
      return json.data as T;
    }

    return json as T;
  }

  // ==================== Template Management ====================

  async createTemplate(data: CreateTemplateRequest): Promise<Template> {
    return this.request<Template>(`${API_PREFIX}/templates`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async listTemplates(params?: {
    name?: string;
    user_id?: string;
    page?: number;
    page_size?: number;
  }): Promise<TemplateListResponse> {
    const searchParams = new URLSearchParams();
    if (params?.name) searchParams.append('name', params.name);
    if (params?.user_id) searchParams.append('user_id', params.user_id);
    if (params?.page) searchParams.append('page', String(params.page));
    if (params?.page_size) searchParams.append('page_size', String(params.page_size));

    const query = searchParams.toString();
    return this.request<TemplateListResponse>(
      `${API_PREFIX}/templates${query ? `?${query}` : ''}`
    );
  }

  async getTemplate(id: string): Promise<Template> {
    return this.request<Template>(`${API_PREFIX}/templates/${id}`);
  }

  async updateTemplate(
    id: string,
    data: UpdateTemplateRequest
  ): Promise<Template> {
    return this.request<Template>(`${API_PREFIX}/templates/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  }

  async deleteTemplate(id: string): Promise<{ message: string }> {
    return this.request<{ message: string }>(`${API_PREFIX}/templates/${id}`, {
      method: 'DELETE',
    });
  }

  // ==================== Sandbox Management ====================

  async createSandbox(data: CreateSandboxRequest): Promise<Sandbox> {
    return this.request<Sandbox>(`${API_PREFIX}/sandboxes`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  // Simple GET query (no metadata filtering)
  async listSandboxes(params?: {
    template_id?: string;
    status?: SandboxStatus;
    pool_state?: string;
    name?: string;
    page?: number;
    page_size?: number;
  }): Promise<SandboxListResponse> {
    const searchParams = new URLSearchParams();
    if (params?.template_id) searchParams.append('template_id', params.template_id);
    if (params?.status) searchParams.append('status', params.status);
    if (params?.pool_state) searchParams.append('pool_state', params.pool_state);
    if (params?.name) searchParams.append('name', params.name);
    if (params?.page) searchParams.append('page', String(params.page));
    if (params?.page_size) searchParams.append('page_size', String(params.page_size));

    const query = searchParams.toString();
    return this.request<SandboxListResponse>(
      `${API_PREFIX}/sandboxes${query ? `?${query}` : ''}`
    );
  }

  // Complex POST query (supports metadata filtering)
  async querySandboxes(params?: {
    template_id?: string;
    status?: SandboxStatus;
    pool_state?: string;
    name?: string;
    metadata?: Record<string, string>;
    page?: number;
    page_size?: number;
  }): Promise<SandboxListResponse> {
    return this.request<SandboxListResponse>(`${API_PREFIX}/sandboxes/query`, {
      method: 'POST',
      body: JSON.stringify(params || {}),
    });
  }

  async getSandbox(id: string): Promise<Sandbox> {
    return this.request<Sandbox>(`${API_PREFIX}/sandboxes/${id}`);
  }

  async deleteSandbox(id: string): Promise<{ message: string }> {
    return this.request<{ message: string }>(`${API_PREFIX}/sandboxes/${id}`, {
      method: 'DELETE',
    });
  }

  async renewSandboxTtl(id: string, ttl = 0): Promise<Sandbox> {
    return this.request<Sandbox>(`${API_PREFIX}/sandboxes/${id}/renew`, {
      method: 'POST',
      body: JSON.stringify({ ttl }),
    });
  }

  // ==================== Execute Command ====================

  async execCommand(
    sandboxId: string,
    data: ExecCommandRequest
  ): Promise<ExecCommandResponse> {
    return this.request<ExecCommandResponse>(
      `${API_PREFIX}/sandboxes/${sandboxId}/exec`,
      {
        method: 'POST',
        body: JSON.stringify(data),
      }
    );
  }

  // ==================== Pool Management ====================

  async listPools(): Promise<PoolListResponse> {
    return this.request<PoolListResponse>(`${API_PREFIX}/pools`);
  }

  async getPoolStatus(templateId: string): Promise<PoolStatus> {
    return this.request<PoolStatus>(`${API_PREFIX}/pools/${templateId}`);
  }

  async createPool(
    templateId: string,
    data: CreatePoolRequest
  ): Promise<PoolStatus> {
    return this.request<PoolStatus>(`${API_PREFIX}/pools/${templateId}`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async updatePool(
    templateId: string,
    data: UpdatePoolRequest
  ): Promise<PoolStatus> {
    return this.request<PoolStatus>(`${API_PREFIX}/pools/${templateId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  }

  async deletePool(templateId: string): Promise<{ message: string }> {
    return this.request<{ message: string }>(
      `${API_PREFIX}/pools/${templateId}`,
      {
        method: 'DELETE',
      }
    );
  }

  // ==================== Resource Statistics ====================

  async getMetricsSnapshot(): Promise<MetricsSnapshot> {
    return this.request<MetricsSnapshot>(`${API_PREFIX}/metrics/snapshot`);
  }

  // ==================== Service Expose Management ====================

  async createExpose(
    sandboxId: string,
    data: CreateServiceExposeRequest
  ): Promise<ServiceExpose> {
    return this.request<ServiceExpose>(
      `${API_PREFIX}/sandboxes/${sandboxId}/exposes`,
      {
        method: 'POST',
        body: JSON.stringify(data),
      }
    );
  }

  async listExposes(sandboxId: string): Promise<{ exposes: ServiceExpose[]; total: number }> {
    return this.request<{ exposes: ServiceExpose[]; total: number }>(
      `${API_PREFIX}/sandboxes/${sandboxId}/exposes`
    );
  }

  async getExpose(exposeId: string): Promise<ServiceExpose> {
    return this.request<ServiceExpose>(`${API_PREFIX}/exposes/${exposeId}`);
  }

  async deleteExpose(exposeId: string): Promise<{ message: string }> {
    return this.request<{ message: string }>(
      `${API_PREFIX}/exposes/${exposeId}`,
      {
        method: 'DELETE',
      }
    );
  }

  // ==================== Webhook Management ====================

  async createWebhook(data: CreateWebhookRequest): Promise<Webhook> {
    return this.request<Webhook>(`${API_PREFIX}/webhooks`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async listWebhooks(params?: { user_id?: string }): Promise<WebhookListResponse> {
    const searchParams = new URLSearchParams();
    if (params?.user_id) searchParams.append('user_id', params.user_id);

    const query = searchParams.toString();
    // request 方法会自动解包 {success: true, data: [...]} 格式，得到数组
    const webhooks = await this.request<Webhook[]>(
      `${API_PREFIX}/webhooks${query ? `?${query}` : ''}`
    );
    // 将数组包装成 WebhookListResponse 格式
    return {
      webhooks: webhooks,
      total: webhooks.length
    };
  }

  async getWebhook(id: string): Promise<Webhook> {
    return this.request<Webhook>(`${API_PREFIX}/webhooks/${id}`);
  }

  async updateWebhook(id: string, data: UpdateWebhookRequest): Promise<Webhook> {
    return this.request<Webhook>(`${API_PREFIX}/webhooks/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  }

  async deleteWebhook(id: string): Promise<{ message: string }> {
    return this.request<{ message: string }>(`${API_PREFIX}/webhooks/${id}`, {
      method: 'DELETE',
    });
  }
}

export const apiClient = new ApiClient(BASE_URL);
