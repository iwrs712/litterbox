// Zustand Store for Sandbox Management - Admin Mode (Multi-Tenant)

import { create } from 'zustand';
import { apiClient } from '@/lib/api';
import type {
  Sandbox,
  Template,
  PoolStatus,
  CreateSandboxRequest,
  CreateTemplateRequest,
  UpdateTemplateRequest,
  CreatePoolRequest,
  UpdatePoolRequest,
  ExecCommandResponse,
  SandboxStatus,
  ServiceExpose,
  CreateServiceExposeRequest,
  Webhook,
  CreateWebhookRequest,
  UpdateWebhookRequest,
} from '@/types/sandbox';

interface SandboxStore {
  // State
  sandboxes: Sandbox[];
  templates: Template[];
  pools: PoolStatus[];
  loading: boolean;
  error: string | null;
  // Service Expose State
  exposes: ServiceExpose[];
  exposesLoading: boolean;
  // Webhook State
  webhooks: Webhook[];
  webhooksLoading: boolean;

  // Sandbox Actions
  fetchSandboxes: (params?: {
    template_id?: string;
    status?: SandboxStatus;
    pool_state?: string;
    name?: string;
    metadata?: Record<string, string>;
  }) => Promise<void>;
  getSandbox: (id: string) => Promise<Sandbox>;
  createSandbox: (data: CreateSandboxRequest) => Promise<void>;
  deleteSandbox: (id: string) => Promise<void>;
  renewSandboxTtl: (sandboxId: string, ttl?: number) => Promise<void>;
  execCommand: (sandboxId: string, command: string[]) => Promise<ExecCommandResponse>;

  // Template Actions - 模板是全局资源
  fetchTemplates: (params?: { name?: string; user_id?: string }) => Promise<void>;
  getTemplate: (id: string) => Promise<Template>;
  createTemplate: (data: CreateTemplateRequest) => Promise<void>;
  updateTemplate: (id: string, data: UpdateTemplateRequest) => Promise<void>;
  deleteTemplate: (id: string) => Promise<void>;

  // Pool Actions
  fetchPools: () => Promise<void>;
  getPoolStatus: (templateId: string) => Promise<PoolStatus>;
  createPool: (templateId: string, data: CreatePoolRequest) => Promise<void>;
  updatePool: (templateId: string, data: UpdatePoolRequest) => Promise<void>;
  deletePool: (templateId: string) => Promise<void>;

  // Service Expose Actions
  fetchExposes: (sandboxId: string) => Promise<void>;
  createExpose: (sandboxId: string, data: CreateServiceExposeRequest) => Promise<void>;
  deleteExpose: (exposeId: string, sandboxId: string) => Promise<void>;
  clearExposes: () => void;

  // Webhook Actions
  fetchWebhooks: (params?: { user_id?: string }) => Promise<void>;
  getWebhook: (id: string) => Promise<Webhook>;
  createWebhook: (data: CreateWebhookRequest) => Promise<void>;
  updateWebhook: (id: string, data: UpdateWebhookRequest) => Promise<void>;
  deleteWebhook: (id: string) => Promise<void>;
  clearWebhooks: () => void;

  // Utility
  clearError: () => void;
}

export const useSandboxStore = create<SandboxStore>((set, get) => ({
  // Initial State
  sandboxes: [],
  templates: [],
  pools: [],
  loading: false,
  error: null,
  // Service Expose Initial State
  exposes: [],
  exposesLoading: false,
  // Webhook Initial State
  webhooks: [],
  webhooksLoading: false,

  // Sandbox Actions
  fetchSandboxes: async (params) => {
    set({ loading: true, error: null });
    try {
      // Use POST query if metadata filtering is needed, otherwise use GET
      const response = params?.metadata && Object.keys(params.metadata).length > 0
        ? await apiClient.querySandboxes(params)
        : await apiClient.listSandboxes(params);
      set({ sandboxes: response.sandboxes, loading: false });
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to fetch sandboxes',
        loading: false,
      });
    }
  },

  getSandbox: async (id: string) => {
    set({ loading: true, error: null });
    try {
      const sandbox = await apiClient.getSandbox(id);
      set({ loading: false });
      return sandbox;
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to fetch sandbox',
        loading: false,
      });
      throw error;
    }
  },

  createSandbox: async (data: CreateSandboxRequest) => {
    set({ loading: true, error: null });
    try {
      const newSandbox = await apiClient.createSandbox(data);
      // 后端已同步等待 pod ready 后才返回，数据可信，直接更新本地列表
      set((state) => ({
        sandboxes: [...state.sandboxes, newSandbox],
        loading: false,
      }));
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to create sandbox',
        loading: false,
      });
      throw error;
    }
  },

  deleteSandbox: async (id: string) => {
    set({ loading: true, error: null });
    try {
      await apiClient.deleteSandbox(id);
      set((state) => ({
        sandboxes: (state.sandboxes || []).filter((s) => s.id !== id),
        loading: false,
      }));
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to delete sandbox',
        loading: false,
      });
      throw error;
    }
  },

  renewSandboxTtl: async (sandboxId: string, ttl = 0) => {
    try {
      await apiClient.renewSandboxTtl(sandboxId, ttl);
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to renew sandbox TTL',
      });
      throw error;
    }
  },

  execCommand: async (sandboxId: string, command: string[]) => {
    try {
      await get().renewSandboxTtl(sandboxId);
      const response = await apiClient.execCommand(sandboxId, {
        command,
        timeout: 30,
      });
      return response;
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to execute command',
      });
      throw error;
    }
  },

  // Template Actions
  fetchTemplates: async (params) => {
    set({ loading: true, error: null });
    try {
      const response = await apiClient.listTemplates(params);
      set({ templates: response.templates, loading: false });
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to fetch templates',
        loading: false,
      });
    }
  },

  getTemplate: async (id: string) => {
    set({ loading: true, error: null });
    try {
      const template = await apiClient.getTemplate(id);
      set({ loading: false });
      return template;
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to fetch template',
        loading: false,
      });
      throw error;
    }
  },

  createTemplate: async (data: CreateTemplateRequest) => {
    set({ loading: true, error: null });
    try {
      const newTemplate = await apiClient.createTemplate(data);
      // 乐观更新，后台补一次刷新确保服务端数据一致
      set((state) => ({
        templates: [...(state.templates || []), newTemplate],
        loading: false,
      }));
      get().fetchTemplates();
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to create template',
        loading: false,
      });
      throw error;
    }
  },

  updateTemplate: async (id: string, data: UpdateTemplateRequest) => {
    set({ loading: true, error: null });
    try {
      const updatedTemplate = await apiClient.updateTemplate(id, data);
      set((state) => ({
        templates: (state.templates || []).map((t) =>
          t.id === id ? updatedTemplate : t
        ),
        loading: false,
      }));
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to update template',
        loading: false,
      });
      throw error;
    }
  },

  deleteTemplate: async (id: string) => {
    set({ loading: true, error: null });
    try {
      await apiClient.deleteTemplate(id);
      // 只维护模板自身状态，不触发其他资源刷新
      set((state) => ({
        templates: (state.templates || []).filter((t) => t.id !== id),
        loading: false,
      }));
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to delete template',
        loading: false,
      });
      throw error;
    }
  },

  // Pool Actions
  fetchPools: async () => {
    set({ loading: true, error: null });
    try {
      const response = await apiClient.listPools();
      set({ pools: response.pools, loading: false });
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to fetch pools',
        loading: false,
      });
    }
  },

  getPoolStatus: async (templateId: string) => {
    set({ loading: true, error: null });
    try {
      const poolStatus = await apiClient.getPoolStatus(templateId);
      set({ loading: false });
      return poolStatus;
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to fetch pool status',
        loading: false,
      });
      throw error;
    }
  },

  createPool: async (templateId: string, data: CreatePoolRequest) => {
    set({ loading: true, error: null });
    try {
      await apiClient.createPool(templateId, data);
      await get().fetchPools();
      set({ loading: false });
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to create pool',
        loading: false,
      });
      throw error;
    }
  },

  updatePool: async (templateId: string, data: UpdatePoolRequest) => {
    set({ loading: true, error: null });
    try {
      await apiClient.updatePool(templateId, data);
      await get().fetchPools();
      set({ loading: false });
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to update pool',
        loading: false,
      });
      throw error;
    }
  },

  deletePool: async (templateId: string) => {
    set({ loading: true, error: null });
    try {
      await apiClient.deletePool(templateId);
      await get().fetchPools();
      set({ loading: false });
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to delete pool',
        loading: false,
      });
      throw error;
    }
  },

  // Service Expose Actions
  fetchExposes: async (sandboxId: string) => {
    set({ exposesLoading: true, error: null });
    try {
      const response = await apiClient.listExposes(sandboxId);
      set({ exposes: response.exposes || [], exposesLoading: false });
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to fetch service exposes',
        exposesLoading: false,
      });
    }
  },

  createExpose: async (sandboxId: string, data: CreateServiceExposeRequest) => {
    set({ exposesLoading: true, error: null });
    try {
      const newExpose = await apiClient.createExpose(sandboxId, data);
      set((state) => ({
        exposes: [...state.exposes, newExpose],
        exposesLoading: false,
      }));
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to create service expose',
        exposesLoading: false,
      });
      throw error;
    }
  },

  deleteExpose: async (exposeId: string, _sandboxId: string) => {
    set({ exposesLoading: true, error: null });
    try {
      await apiClient.deleteExpose(exposeId);
      set((state) => ({
        exposes: state.exposes.filter((e) => e.id !== exposeId),
        exposesLoading: false,
      }));
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to delete service expose',
        exposesLoading: false,
      });
      throw error;
    }
  },

  clearExposes: () => {
    set({ exposes: [], exposesLoading: false });
  },

  // Webhook Actions
  fetchWebhooks: async (params) => {
    set({ webhooksLoading: true, error: null });
    try {
      const response = await apiClient.listWebhooks(params);
      set({ webhooks: response.webhooks || [], webhooksLoading: false });
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to fetch webhooks',
        webhooksLoading: false,
      });
    }
  },

  getWebhook: async (id: string) => {
    set({ webhooksLoading: true, error: null });
    try {
      const webhook = await apiClient.getWebhook(id);
      set({ webhooksLoading: false });
      return webhook;
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to fetch webhook',
        webhooksLoading: false,
      });
      throw error;
    }
  },

  createWebhook: async (data: CreateWebhookRequest) => {
    set({ webhooksLoading: true, error: null });
    try {
      const newWebhook = await apiClient.createWebhook(data);
      set((state) => ({
        webhooks: [...state.webhooks, newWebhook],
        webhooksLoading: false,
      }));
      // 后台刷新确保服务端数据一致
      get().fetchWebhooks({ user_id: data.user_id });
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to create webhook',
        webhooksLoading: false,
      });
      throw error;
    }
  },

  updateWebhook: async (id: string, data: UpdateWebhookRequest) => {
    set({ webhooksLoading: true, error: null });
    try {
      const updatedWebhook = await apiClient.updateWebhook(id, data);
      set((state) => ({
        webhooks: state.webhooks.map((w) => w.id === id ? updatedWebhook : w),
        webhooksLoading: false,
      }));
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to update webhook',
        webhooksLoading: false,
      });
      throw error;
    }
  },

  deleteWebhook: async (id: string) => {
    set({ webhooksLoading: true, error: null });
    try {
      await apiClient.deleteWebhook(id);
      set((state) => ({
        webhooks: state.webhooks.filter((w) => w.id !== id),
        webhooksLoading: false,
      }));
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to delete webhook',
        webhooksLoading: false,
      });
      throw error;
    }
  },

  clearWebhooks: () => {
    set({ webhooks: [], webhooksLoading: false });
  },

  // Utility
  clearError: () => {
    set({ error: null });
  },
}));
