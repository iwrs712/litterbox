export type Language = 'en' | 'zh';

export interface Translations {
  common: {
    back: string;
    confirm: string;
    cancel: string;
    delete: string;
    create: string;
    edit: string;
    save: string;
    update: string;
    close: string;
    loading: string;
    error: string;
    success: string;
    lightMode: string;
    darkMode: string;
    refresh: string;
    actions: string;
  };
  nav: {
    dashboard: string;
    sandboxes: string;
    templates: string;
    pools: string;
    webhooks: string;
    metrics: string;
  };
  tenant: {
    current: string;
    selector: string;
    switchTenant: string;
  };
  header: {
    title: string;
    subtitle: string;
  };
  auth: {
    openButton: string;
    dialogTitle: string;
    dialogDescription: string;
    tokenLabel: string;
    tokenPlaceholder: string;
    configured: string;
    notConfigured: string;
    saveToken: string;
    clearToken: string;
  };
  footer: {
    poweredBy: string;
    copyright: string;
  };
  sandbox: {
    status: {
      created: string;
      running: string;
      stopped: string;
    };
    pool: {
      managed: string;
      userCreated: string;
      available: string;
      allocated: string;
    };
    list: {
      title: string;
      createButton: string;
      noSandboxes: string;
      columns: {
        id: string;
        name: string;
        template: string;
        status: string;
        resources: string;
        poolInfo: string;
        createdAt: string;
        actions: string;
      };
    };
    detail: {
      title: string;
      basicInfo: string;
      loading: string;
      notFound: string;
      backToList: string;
      delete: string;
      resources: string;
      cpuCount: string;
      memory: string;
      templateInfo: string;
      templateId: string;
      image: string;
      status: string;
      poolInfo: string;
      poolState: string;
      poolManagedDescription: string;
      metadata: string;
      sandboxId: string;
      created: string;
      updated: string;
      customMetadata: string;
      executeCommand: string;
    };
    create: {
      title: string;
      nameLabel: string;
      namePlaceholder: string;
      templateLabel: string;
      templatePlaceholder: string;
      metadataLabel: string;
      creating: string;
    };
    delete: {
      title: string;
      description: string;
      confirm: string;
      deleting: string;
    };
    terminal: {
      title: string;
      connecting: string;
      connected: string;
      disconnected: string;
      error: string;
      reconnect: string;
    };
  };
  template: {
    title: string;
    list: {
      title: string;
      subtitle: string;
      description: string;
      allTemplates: string;
      createButton: string;
      editButton: string;
      deleteButton: string;
      noTemplates: string;
      columns: {
        id: string;
        name: string;
        image: string;
        resources: string;
        poolSize: string;
        createdAt: string;
        actions: string;
      };
    };
    detail: {
      title: string;
      basicInfo: string;
      resources: string;
      poolConfig: string;
      metadata: string;
      loading: string;
      notFound: string;
      backToList: string;
      computeResources: string;
      cpuCount: string;
      memory: string;
      imageInfo: string;
      image: string;
      poolStatus: string;
      poolReady: string;
      poolNotReady: string;
      configurePool: string;
      minReady: string;
      targetReady: string;
      readyCount: string;
      allocated: string;
      creating: string;
      failed: string;
      terminating: string;
      poolProgress: string;
      poolDisabled: string;
      poolDisabledDescription: string;
      loadingPool: string;
      templateId: string;
      created: string;
      updated: string;
    };
    create: {
      title: string;
      description: string;
      nameLabel: string;
      namePlaceholder: string;
      imageLabel: string;
      imagePlaceholder: string;
      cpuLabel: string;
      memoryLabel: string;
      creating: string;
    };
    edit: {
      title: string;
      description: string;
      idLabel: string;
      nameLabel: string;
      imageLabel: string;
      cpuLabel: string;
      memoryLabel: string;
      updating: string;
    };
    delete: {
      title: string;
      description: string;
      note: string;
      noteText: string;
      confirm: string;
      deleting: string;
    };
    pool: {
      title: string;
      description: string;
      configure: string;
      enable: string;
      disable: string;
      minReadyLabel: string;
      minReadyDescription: string;
      targetReadyLabel: string;
      targetReadyDescription: string;
      maxCreatingLabel: string;
      maxCreatingDescription: string;
      updating: string;
      status: {
        minReady: string;
        targetReady: string;
        ready: string;
        allocated: string;
        creating: string;
        failed: string;
        terminating: string;
        total: string;
      };
    };
  };
  dashboard: {
    title: string;
    subtitle: string;
    welcome: string;
    resourceUsage: string;
    poolStatus: string;
    pools: {
      title: string;
      description: string;
      createButton: string;
      noPools: string;
      noPoolsDescription: string;
      columns: {
        template: string;
        minReady: string;
        targetReady: string;
        ready: string;
        allocated: string;
        creating: string;
        failed: string;
        status: string;
        actions: string;
      };
      create: {
        title: string;
        description: string;
        selectTemplate: string;
        selectTemplatePlaceholder: string;
        minReadyLabel: string;
        minReadyPlaceholder: string;
        targetReadyLabel: string;
        targetReadyPlaceholder: string;
        maxCreatingLabel: string;
        maxCreatingPlaceholder: string;
        advancedSettings: string;
        creating: string;
      };
      edit: {
        title: string;
        description: string;
        updating: string;
      };
      delete: {
        title: string;
        description: string;
        warning: string;
        deleting: string;
      };
    };
    loading: string;
    noTenant: string;
    noData: string;
    lastUpdated: string;
    totalSandboxes: string;
    running: string;
    cpuCores: string;
    memory: string;
    totalAllocated: string;
    poolStatistics: string;
    totalPools: string;
    poolSandboxes: string;
    allocatedFromPool: string;
    noPools: string;
    noPoolsDescription: string;
    targetReady: string;
    ready: string;
    allocated: string;
    creating: string;
    failed: string;
    total: string;
    notReady: string;
    poolExhausted: string;
    warming: string;
    healthy: string;
  };
  webhook: {
    title: string;
    list: {
      title: string;
      description: string;
      createButton: string;
      editButton: string;
      deleteButton: string;
      noWebhooks: string;
      columns: {
        name: string;
        url: string;
        events: string;
        templates: string;
        enabled: string;
        createdAt: string;
        actions: string;
      };
    };
    create: {
      title: string;
      description: string;
      nameLabel: string;
      namePlaceholder: string;
      userIdLabel: string;
      userIdPlaceholder: string;
      urlLabel: string;
      urlPlaceholder: string;
      tokenLabel: string;
      tokenPlaceholder: string;
      templatesLabel: string;
      templatesPlaceholder: string;
      eventsLabel: string;
      enabledLabel: string;
      retryLabel: string;
      maxAttemptsLabel: string;
      intervalMsLabel: string;
      timeoutMsLabel: string;
      creating: string;
    };
    edit: {
      title: string;
      description: string;
      updating: string;
    };
    delete: {
      title: string;
      description: string;
      confirm: string;
      deleting: string;
    };
    events: {
      sandbox_started: string;
      sandbox_ready: string;
      sandbox_deleted: string;
    };
    status: {
      enabled: string;
      disabled: string;
    };
  };
}

const en: Translations = {
  common: {
    back: 'Back',
    confirm: 'Confirm',
    cancel: 'Cancel',
    delete: 'Delete',
    create: 'Create',
    edit: 'Edit',
    save: 'Save',
    update: 'Update',
    close: 'Close',
    loading: 'Loading...',
    error: 'Error',
    success: 'Success',
    lightMode: 'Light Mode',
    darkMode: 'Dark Mode',
    refresh: 'Refresh',
    actions: 'Actions',
  },
  nav: {
    dashboard: 'Dashboard',
    sandboxes: 'Sandboxes',
    templates: 'Templates',
    pools: 'Pools',
    webhooks: 'Webhooks',
    metrics: 'Metrics',
  },
  tenant: {
    current: 'Tenant',
    selector: 'Select Tenant',
    switchTenant: 'Switch Tenant',
  },
  header: {
    title: 'Litterbox',
    subtitle: 'Sandbox Orchestration Platform',
  },
  auth: {
    openButton: 'API token settings',
    dialogTitle: 'API Bearer Token',
    dialogDescription: 'Configure the token used in dashboard API and terminal requests.',
    tokenLabel: 'Bearer Token',
    tokenPlaceholder: 'Paste API bearer token',
    configured: 'Token configured',
    notConfigured: 'No token configured',
    saveToken: 'Save Token',
    clearToken: 'Clear Token',
  },
  footer: {
    poweredBy: 'Powered by Litterbox',
    copyright: '© 2026 Litterbox. All rights reserved.',
  },
  sandbox: {
    status: {
      created: 'Created',
      running: 'Running',
      stopped: 'Stopped',
    },
    pool: {
      managed: 'Pool Managed',
      userCreated: 'User Created',
      available: 'Available',
      allocated: 'Allocated',
    },
    list: {
      title: 'Sandboxes',
      createButton: 'Create Sandbox',
      noSandboxes: 'No sandboxes found',
      columns: {
        id: 'ID',
        name: 'Name',
        template: 'Template',
        status: 'Status',
        resources: 'Resources',
        poolInfo: 'Pool Info',
        createdAt: 'Created At',
        actions: 'Actions',
      },
    },
    detail: {
      title: 'Sandbox Details',
      basicInfo: 'Basic Information',
      loading: 'Loading sandbox...',
      notFound: 'Sandbox not found',
      backToList: 'Back to Sandboxes',
      delete: 'Delete Sandbox',
      resources: 'Resources',
      cpuCount: 'CPU',
      memory: 'Memory',
      templateInfo: 'Template Information',
      templateId: 'Template ID',
      image: 'Image',
      status: 'Status',
      poolInfo: 'Pool Information',
      poolState: 'Pool State',
      poolManagedDescription: 'This sandbox is managed by a pool and may be replenished automatically.',
      metadata: 'Metadata',
      sandboxId: 'Sandbox ID',
      created: 'Created',
      updated: 'Updated',
      customMetadata: 'Custom Metadata',
      executeCommand: 'Execute Command',
    },
    create: {
      title: 'Create New Sandbox',
      nameLabel: 'Sandbox Name',
      namePlaceholder: 'Enter sandbox name',
      templateLabel: 'Template',
      templatePlaceholder: 'Select a template',
      metadataLabel: 'Metadata (Optional)',
      creating: 'Creating...',
    },
    delete: {
      title: 'Delete Sandbox',
      description: 'Are you sure you want to delete this sandbox? This action cannot be undone.',
      confirm: 'Yes, delete sandbox',
      deleting: 'Deleting...',
    },
    terminal: {
      title: 'Terminal',
      connecting: 'Connecting...',
      connected: 'Connected',
      disconnected: 'Disconnected',
      error: 'Connection Error',
      reconnect: 'Reconnect',
    },
  },
  template: {
    title: 'Templates',
    list: {
      title: 'Templates',
      subtitle: 'Manage sandbox templates',
      description: 'Manage sandbox templates',
      allTemplates: 'All Templates',
      createButton: 'Create Template',
      editButton: 'Edit',
      deleteButton: 'Delete',
      noTemplates: 'No templates found',
      columns: {
        id: 'ID',
        name: 'Name',
        image: 'Image',
        resources: 'Resources',
        poolSize: 'Pool Size',
        createdAt: 'Created At',
        actions: 'Actions',
      },
    },
    detail: {
      title: 'Template Details',
      basicInfo: 'Basic Information',
      resources: 'Resources',
      poolConfig: 'Pool Configuration',
      metadata: 'Metadata',
      loading: 'Loading template...',
      notFound: 'Template not found',
      backToList: 'Back to Templates',
      computeResources: 'Compute Resources',
      cpuCount: 'CPU (millicores)',
      memory: 'Memory',
      imageInfo: 'Image Info',
      image: 'Container Image',
      poolStatus: 'Pool Status',
      poolReady: 'Active',
      poolNotReady: 'Inactive',
      configurePool: 'Configure Pool',
      minReady: 'Min Ready',
      targetReady: 'Target Ready',
      readyCount: 'Ready',
      allocated: 'Allocated',
      creating: 'Creating',
      failed: 'Failed',
      terminating: 'Terminating',
      poolProgress: 'Pool Fill Progress',
      poolDisabled: 'Pool is disabled',
      poolDisabledDescription: 'Set min_ready > 0 to enable the pool',
      loadingPool: 'Loading pool status...',
      templateId: 'Template ID',
      created: 'Created',
      updated: 'Updated',
    },
    create: {
      title: 'Create New Template',
      description: 'Configure a new template for creating sandboxes',
      nameLabel: 'Template Name',
      namePlaceholder: 'Enter template name',
      imageLabel: 'Container Image',
      imagePlaceholder: 'python:3.11-slim',
      cpuLabel: 'CPU Cores',
      memoryLabel: 'Memory (MB)',
      creating: 'Creating...',
    },
    edit: {
      title: 'Edit Template',
      description: 'Update template configuration',
      idLabel: 'Template ID',
      nameLabel: 'Template Name',
      imageLabel: 'Container Image',
      cpuLabel: 'CPU Cores',
      memoryLabel: 'Memory (MB)',
      updating: 'Updating...',
    },
    delete: {
      title: 'Delete Template',
      description: 'Are you sure you want to delete this template?',
      note: 'Note:',
      noteText: 'Deleting a template will affect all pools and sandboxes using it.',
      confirm: 'Delete',
      deleting: 'Deleting...',
    },
    pool: {
      title: 'Pool Configuration',
      description: 'Configure the warm pool settings for this template.',
      configure: 'Configure Pool',
      enable: 'Enable Pool',
      disable: 'Disable Pool',
      minReadyLabel: 'Min Ready',
      minReadyDescription: 'Low-water trigger threshold. Set to 0 to disable pool.',
      targetReadyLabel: 'Target Ready',
      targetReadyDescription: 'Fill target - how many sandboxes to keep ready.',
      maxCreatingLabel: 'Max Creating',
      maxCreatingDescription: 'Maximum concurrent sandbox creations (1-20).',
      updating: 'Updating...',
      status: {
        minReady: 'Min Ready',
        targetReady: 'Target Ready',
        ready: 'Ready',
        allocated: 'Allocated',
        creating: 'Creating',
        failed: 'Failed',
        terminating: 'Terminating',
        total: 'Total',
      },
    },
  },
  dashboard: {
    title: 'Dashboard',
    subtitle: 'Real-time resource monitoring and pool status',
    welcome: 'Welcome to Litterbox',
    resourceUsage: 'Resource Usage',
    poolStatus: 'Pool Status',
    pools: {
      title: 'Warm Pools',
      description: 'Manage pre-created sandbox pools for instant allocation',
      createButton: 'Create Pool',
      noPools: 'No pools configured',
      noPoolsDescription: 'Click "Create Pool" to configure a warm pool for a template',
      columns: {
        template: 'Template',
        minReady: 'Min Ready',
        targetReady: 'Target Ready',
        ready: 'Ready',
        allocated: 'Allocated',
        creating: 'Creating',
        failed: 'Failed',
        status: 'Status',
        actions: 'Actions',
      },
      create: {
        title: 'Create Warm Pool',
        description: 'Configure a new warm pool for instant sandbox allocation',
        selectTemplate: 'Template',
        selectTemplatePlaceholder: 'Select a template',
        minReadyLabel: 'Min Ready',
        minReadyPlaceholder: 'Low-water trigger threshold (1-50)',
        targetReadyLabel: 'Target Ready',
        targetReadyPlaceholder: 'Fill target - sandboxes to keep ready (1-100)',
        maxCreatingLabel: 'Max Creating',
        maxCreatingPlaceholder: 'Max concurrent creating sandboxes (1-20)',
        advancedSettings: 'Advanced Settings',
        creating: 'Creating...',
      },
      edit: {
        title: 'Update Pool Configuration',
        description: 'Adjust pool settings for the selected template',
        updating: 'Updating...',
      },
      delete: {
        title: 'Delete Pool',
        description: 'Are you sure you want to delete this pool?',
        warning: 'This will terminate all available and creating sandboxes. Allocated sandboxes will continue running.',
        deleting: 'Deleting...',
      },
    },
    loading: 'Loading dashboard...',
    noTenant: 'Please select a tenant',
    noData: 'No data available',
    lastUpdated: 'Last updated',
    totalSandboxes: 'Total Sandboxes',
    running: 'running',
    cpuCores: 'CPU Cores',
    memory: 'Memory',
    totalAllocated: 'Total allocated',
    poolStatistics: 'Pool Statistics',
    totalPools: 'Total Pools',
    poolSandboxes: 'Pool Sandboxes',
    allocatedFromPool: 'Allocated from Pool',
    noPools: 'No pools configured',
    noPoolsDescription: 'Create templates and configure pool sizes to enable warm pools',
    targetReady: 'Target Ready',
    ready: 'Ready',
    allocated: 'Allocated',
    creating: 'Creating',
    failed: 'Failed',
    total: 'Total',
    notReady: 'Not Ready',
    poolExhausted: 'Pool exhausted',
    warming: 'Warming up',
    healthy: 'Healthy',
  },
  webhook: {
    title: 'Webhooks',
    list: {
      title: 'Webhooks',
      description: 'Manage webhook notifications for sandbox events',
      createButton: 'Create Webhook',
      editButton: 'Edit',
      deleteButton: 'Delete',
      noWebhooks: 'No webhooks found',
      columns: {
        name: 'Name',
        url: 'URL',
        events: 'Events',
        templates: 'Templates',
        enabled: 'Status',
        createdAt: 'Created At',
        actions: 'Actions',
      },
    },
    create: {
      title: 'Create New Webhook',
      description: 'Configure webhook notifications for sandbox lifecycle events',
      nameLabel: 'Webhook Name',
      namePlaceholder: 'Enter webhook name',
      userIdLabel: 'User ID',
      userIdPlaceholder: 'Enter user ID',
      urlLabel: 'Webhook URL',
      urlPlaceholder: 'https://example.com/webhook',
      tokenLabel: 'Authentication Token',
      tokenPlaceholder: 'Enter authentication token',
      templatesLabel: 'Template IDs (comma-separated)',
      templatesPlaceholder: 'template-1, template-2',
      eventsLabel: 'Events',
      enabledLabel: 'Enable Webhook',
      retryLabel: 'Retry Configuration',
      maxAttemptsLabel: 'Max Retry Attempts',
      intervalMsLabel: 'Retry Interval (ms)',
      timeoutMsLabel: 'Request Timeout (ms)',
      creating: 'Creating...',
    },
    edit: {
      title: 'Edit Webhook',
      description: 'Update webhook configuration',
      updating: 'Updating...',
    },
    delete: {
      title: 'Delete Webhook',
      description: 'Are you sure you want to delete this webhook?',
      confirm: 'Delete',
      deleting: 'Deleting...',
    },
    events: {
      sandbox_started: 'Sandbox Started',
      sandbox_ready: 'Sandbox Ready',
      sandbox_deleted: 'Sandbox Deleted',
    },
    status: {
      enabled: 'Enabled',
      disabled: 'Disabled',
    },
  },
};

const zh: Translations = {
  common: {
    back: '返回',
    confirm: '确认',
    cancel: '取消',
    delete: '删除',
    create: '创建',
    edit: '编辑',
    save: '保存',
    update: '更新',
    close: '关闭',
    loading: '加载中...',
    error: '错误',
    success: '成功',
    lightMode: '浅色模式',
    darkMode: '深色模式',
    refresh: '刷新',
    actions: '操作',
  },
  nav: {
    dashboard: '仪表板',
    sandboxes: '沙盒',
    templates: '模板',
    pools: '池',
    webhooks: 'Webhook',
    metrics: '指标',
  },
  tenant: {
    current: '租户',
    selector: '选择租户',
    switchTenant: '切换租户',
  },
  header: {
    title: 'Litterbox',
    subtitle: '沙盒编排平台',
  },
  auth: {
    openButton: 'API 令牌设置',
    dialogTitle: 'API Bearer 令牌',
    dialogDescription: '配置 Dashboard 调用 API 与终端连接时使用的令牌。',
    tokenLabel: 'Bearer 令牌',
    tokenPlaceholder: '粘贴 API Bearer 令牌',
    configured: '已配置令牌',
    notConfigured: '未配置令牌',
    saveToken: '保存令牌',
    clearToken: '清除令牌',
  },
  footer: {
    poweredBy: 'Powered by Litterbox',
    copyright: '© 2026 Litterbox. 保留所有权利。',
  },
  sandbox: {
    status: {
      created: '已创建',
      running: '运行中',
      stopped: '已停止',
    },
    pool: {
      managed: '池管理',
      userCreated: '用户创建',
      available: '可用',
      allocated: '已分配',
    },
    list: {
      title: '沙盒列表',
      createButton: '创建沙盒',
      noSandboxes: '未找到沙盒',
      columns: {
        id: 'ID',
        name: '名称',
        template: '模板',
        status: '状态',
        resources: '资源',
        poolInfo: '池信息',
        createdAt: '创建时间',
        actions: '操作',
      },
    },
    detail: {
      title: '沙盒详情',
      basicInfo: '基本信息',
      loading: '加载沙盒中...',
      notFound: '未找到沙盒',
      backToList: '返回沙盒列表',
      delete: '删除沙盒',
      resources: '资源配置',
      cpuCount: 'CPU',
      memory: '内存',
      templateInfo: '模板信息',
      templateId: '模板 ID',
      image: '镜像',
      status: '状态',
      poolInfo: '池信息',
      poolState: '池状态',
      poolManagedDescription: '该沙盒由池管理，系统可能会自动补充池容量。',
      metadata: '元数据',
      sandboxId: '沙盒 ID',
      created: '创建时间',
      updated: '更新时间',
      customMetadata: '自定义元数据',
      executeCommand: '执行命令',
    },
    create: {
      title: '创建新沙盒',
      nameLabel: '沙盒名称',
      namePlaceholder: '输入沙盒名称',
      templateLabel: '模板',
      templatePlaceholder: '选择模板',
      metadataLabel: '元数据（可选）',
      creating: '创建中...',
    },
    delete: {
      title: '删除沙盒',
      description: '确定要删除此沙盒吗？此操作无法撤销。',
      confirm: '是的，删除沙盒',
      deleting: '删除中...',
    },
    terminal: {
      title: '终端',
      connecting: '连接中...',
      connected: '已连接',
      disconnected: '已断开',
      error: '连接错误',
      reconnect: '重新连接',
    },
  },
  template: {
    title: '模板',
    list: {
      title: '模板列表',
      subtitle: '管理沙盒模板',
      description: '管理沙盒模板',
      allTemplates: '全部模板',
      createButton: '创建模板',
      editButton: '编辑',
      deleteButton: '删除',
      noTemplates: '未找到模板',
      columns: {
        id: 'ID',
        name: '名称',
        image: '镜像',
        resources: '资源',
        poolSize: '池大小',
        createdAt: '创建时间',
        actions: '操作',
      },
    },
    detail: {
      title: '模板详情',
      basicInfo: '基本信息',
      resources: '资源配置',
      poolConfig: '池配置',
      metadata: '元数据',
      loading: '加载模板中...',
      notFound: '未找到模板',
      backToList: '返回模板列表',
      computeResources: '计算资源',
      cpuCount: 'CPU（毫核）',
      memory: '内存',
      imageInfo: '镜像信息',
      image: '容器镜像',
      poolStatus: '池状态',
      poolReady: '活跃',
      poolNotReady: '未活跃',
      configurePool: '配置池',
      minReady: '最小就绪数',
      targetReady: '目标就绪数',
      readyCount: '就绪',
      allocated: '已分配',
      creating: '创建中',
      failed: '失败',
      terminating: '终止中',
      poolProgress: '池填充进度',
      poolDisabled: '池已禁用',
      poolDisabledDescription: '设置 min_ready > 0 以启用池',
      loadingPool: '加载池状态中...',
      templateId: '模板 ID',
      created: '创建时间',
      updated: '更新时间',
    },
    create: {
      title: '创建新模板',
      description: '配置新的沙盒模板',
      nameLabel: '模板名称',
      namePlaceholder: '输入模板名称',
      imageLabel: '容器镜像',
      imagePlaceholder: 'python:3.11-slim',
      cpuLabel: 'CPU 核心数',
      memoryLabel: '内存 (MB)',
      creating: '创建中...',
    },
    edit: {
      title: '编辑模板',
      description: '更新模板配置',
      idLabel: '模板 ID',
      nameLabel: '模板名称',
      imageLabel: '容器镜像',
      cpuLabel: 'CPU 核心数',
      memoryLabel: '内存 (MB)',
      updating: '更新中...',
    },
    delete: {
      title: '删除模板',
      description: '确定要删除此模板吗？',
      note: '注意：',
      noteText: '删除模板将影响所有使用它的池和沙盒。',
      confirm: '删除',
      deleting: '删除中...',
    },
    pool: {
      title: '池配置',
      description: '为该模板配置预热池设置。',
      configure: '配置池',
      enable: '启用池',
      disable: '禁用池',
      minReadyLabel: '最小就绪数',
      minReadyDescription: '低水位触发阈值。设为 0 可禁用池。',
      targetReadyLabel: '目标就绪数',
      targetReadyDescription: '填充目标 - 保持多少个沙盒处于就绪状态。',
      maxCreatingLabel: '最大创建数',
      maxCreatingDescription: '最大并发创建沙盒数（1-20）。',
      updating: '更新中...',
      status: {
        minReady: '最小就绪数',
        targetReady: '目标就绪数',
        ready: '就绪',
        allocated: '已分配',
        creating: '创建中',
        failed: '失败',
        terminating: '终止中',
        total: '总计',
      },
    },
  },
  dashboard: {
    title: '仪表板',
    subtitle: '实时资源监控和池状态',
    welcome: '欢迎使用 Litterbox',
    resourceUsage: '资源使用情况',
    poolStatus: '池状态',
    pools: {
      title: '预热池',
      description: '管理预创建的沙盒池，实现即时分配',
      createButton: '创建池',
      noPools: '未配置池',
      noPoolsDescription: '点击"创建池"为模板配置预热池',
      columns: {
        template: '模板',
        minReady: '最小就绪',
        targetReady: '目标就绪',
        ready: '就绪',
        allocated: '已分配',
        creating: '创建中',
        failed: '失败',
        status: '状态',
        actions: '操作',
      },
      create: {
        title: '创建预热池',
        description: '为模板配置新的预热池以实现即时沙盒分配',
        selectTemplate: '模板',
        selectTemplatePlaceholder: '选择模板',
        minReadyLabel: '最小就绪数',
        minReadyPlaceholder: '低水位触发阈值 (1-50)',
        targetReadyLabel: '目标就绪数',
        targetReadyPlaceholder: '填充目标 - 保持就绪的沙盒数 (1-100)',
        maxCreatingLabel: '最大创建数',
        maxCreatingPlaceholder: '最大并发创建沙盒数 (1-20)',
        advancedSettings: '高级设置',
        creating: '创建中...',
      },
      edit: {
        title: '更新池配置',
        description: '调整所选模板的池设置',
        updating: '更新中...',
      },
      delete: {
        title: '删除池',
        description: '确定要删除此池吗？',
        warning: '这将终止所有可用和创建中的沙盒。已分配的沙盒将继续运行。',
        deleting: '删除中...',
      },
    },
    loading: '加载仪表板中...',
    noTenant: '请选择租户',
    noData: '无可用数据',
    lastUpdated: '最后更新',
    totalSandboxes: '总沙盒数',
    running: '运行中',
    cpuCores: 'CPU 核心',
    memory: '内存',
    totalAllocated: '总分配量',
    poolStatistics: '池统计',
    totalPools: '总池数',
    poolSandboxes: '池沙盒数',
    allocatedFromPool: '从池分配',
    noPools: '未配置池',
    noPoolsDescription: '创建模板并配置池大小以启用预热池',
    targetReady: '目标就绪',
    ready: '就绪',
    allocated: '已分配',
    creating: '创建中',
    failed: '失败',
    total: '总计',
    notReady: '未就绪',
    poolExhausted: '池已耗尽',
    warming: '预热中',
    healthy: '健康',
  },
  webhook: {
    title: 'Webhook',
    list: {
      title: 'Webhook 列表',
      description: '管理沙盒事件的 Webhook 通知',
      createButton: '创建 Webhook',
      editButton: '编辑',
      deleteButton: '删除',
      noWebhooks: '未找到 Webhook',
      columns: {
        name: '名称',
        url: 'URL',
        events: '事件',
        templates: '模板',
        enabled: '状态',
        createdAt: '创建时间',
        actions: '操作',
      },
    },
    create: {
      title: '创建新 Webhook',
      description: '为沙盒生命周期事件配置 Webhook 通知',
      nameLabel: 'Webhook 名称',
      namePlaceholder: '输入 Webhook 名称',
      userIdLabel: '用户 ID',
      userIdPlaceholder: '输入用户 ID',
      urlLabel: 'Webhook URL',
      urlPlaceholder: 'https://example.com/webhook',
      tokenLabel: '认证令牌',
      tokenPlaceholder: '输入认证令牌',
      templatesLabel: '模板 ID（逗号分隔）',
      templatesPlaceholder: 'template-1, template-2',
      eventsLabel: '事件',
      enabledLabel: '启用 Webhook',
      retryLabel: '重试配置',
      maxAttemptsLabel: '最大重试次数',
      intervalMsLabel: '重试间隔（毫秒）',
      timeoutMsLabel: '请求超时（毫秒）',
      creating: '创建中...',
    },
    edit: {
      title: '编辑 Webhook',
      description: '更新 Webhook 配置',
      updating: '更新中...',
    },
    delete: {
      title: '删除 Webhook',
      description: '确定要删除此 Webhook 吗？',
      confirm: '删除',
      deleting: '删除中...',
    },
    events: {
      sandbox_started: '沙盒已启动',
      sandbox_ready: '沙盒已就绪',
      sandbox_deleted: '沙盒已删除',
    },
    status: {
      enabled: '已启用',
      disabled: '已禁用',
    },
  },
};

export const translations: Record<Language, Translations> = {
  en,
  zh,
};
