import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useSandboxStore } from '@/store/sandboxStore';
import { useApp } from '@/contexts/AppContext';
import type { Template, CreateTemplateRequest, UpdateTemplateRequest } from '@/types/sandbox';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { ErrorAlert } from '@/components/ErrorAlert';
import { Plus, Edit, Trash2, RefreshCw, FileCode, Eye, Loader2 } from 'lucide-react';
import { formatDistanceToNow } from 'date-fns';

export function Templates() {
  const { t } = useApp();
  const { templates, fetchTemplates, createTemplate, updateTemplate, deleteTemplate, loading, error, clearError } = useSandboxStore();

  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [showEditDialog, setShowEditDialog] = useState(false);
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const [selectedTemplate, setSelectedTemplate] = useState<Template | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  // Filter state
  const [userIdFilter, setUserIdFilter] = useState('');

  const [formData, setFormData] = useState({
    id: '',
    name: '',
    image: 'ubuntu:24.04',
    command: '', // 容器启动命令（单行字符串，提交时转为数组）
    env: '', // 环境变量（多行文本，每行一个 KEY=VALUE）
    host_path_mounts: '', // 主机路径挂载（JSON格式或多行格式）
    lifecycle: '', // Sandbox lifecycle hooks (JSON)
    cpu_millicores: 1000, // 默认 1 核 = 1000m
    cpu_request: undefined as number | undefined,
    memory_mb: 512,
    memory_request: undefined as number | undefined,
    ttl_seconds: undefined as number | undefined, // TTL秒数（300-86400）
    user_id: '', // user_id 字段（将存入 metadata）
    metadata: {} as Record<string, any>,
  });
  const [showAdvanced, setShowAdvanced] = useState(false);

  useEffect(() => {
    // 模板是全局资源，不再需要 tenant_id
    fetchTemplates();
  }, [fetchTemplates]);

  const handleRefresh = () => {
    setActionLoading('refresh');
    fetchTemplates(userIdFilter ? { user_id: userIdFilter } : undefined);
    setTimeout(() => setActionLoading(null), 500);
  };

  const handleFilterByUserId = () => {
    setActionLoading('filter');
    fetchTemplates(userIdFilter ? { user_id: userIdFilter } : undefined);
    setTimeout(() => setActionLoading(null), 500);
  };

  const handleClearFilter = () => {
    setUserIdFilter('');
    setActionLoading('clear-filter');
    fetchTemplates();
    setTimeout(() => setActionLoading(null), 500);
  };

  const handleCreate = async () => {
    setActionLoading('create');
    try {
      // 准备 metadata，将 user_id 存入其中
      const metadata: Record<string, any> = { ...formData.metadata };
      if (formData.user_id.trim()) {
        metadata.user_id = formData.user_id.trim();
      }

      // 解析 env 从多行文本到数组
      const envArray = formData.env
        .split('\n')
        .map(line => line.trim())
        .filter(line => line.length > 0);

      // 解析 host_path_mounts 从 JSON 文本到对象数组
      let hostPathMounts = undefined;
      if (formData.host_path_mounts.trim()) {
        try {
          hostPathMounts = JSON.parse(formData.host_path_mounts.trim());
        } catch (e) {
          console.error('Failed to parse host_path_mounts:', e);
          // 如果解析失败，尝试留空
        }
      }

      let lifecycle = undefined;
      if (formData.lifecycle.trim()) {
        try {
          lifecycle = JSON.parse(formData.lifecycle.trim());
        } catch (e) {
          console.error('Failed to parse lifecycle:', e);
          window.alert('Lifecycle must be valid JSON.');
          return;
        }
      }

      await createTemplate({
        id: formData.id || undefined, // 空字符串转为 undefined，让后端自动生成
        name: formData.name,
        image: formData.image,
        command: formData.command.trim() || undefined, // command 作为字符串
        env: envArray.length > 0 ? envArray : undefined,
        host_path_mounts: hostPathMounts,
        lifecycle,
        cpu_millicores: formData.cpu_millicores,
        cpu_request: formData.cpu_request,
        memory_mb: formData.memory_mb,
        memory_request: formData.memory_request,
        ttl_seconds: formData.ttl_seconds,
        metadata: Object.keys(metadata).length > 0 ? metadata : undefined,
      });
      setShowCreateDialog(false);
      resetForm();
    } catch (err) {
      // Error handled by store
    } finally {
      setActionLoading(null);
    }
  };

  const handleEdit = async () => {
    if (!selectedTemplate) return;
    setActionLoading('edit');
    try {
      // 准备 metadata，将 user_id 存入其中
      const metadata: Record<string, any> = { ...formData.metadata };
      if (formData.user_id.trim()) {
        metadata.user_id = formData.user_id.trim();
      } else {
        // 如果 user_id 为空，从 metadata 中删除
        delete metadata.user_id;
      }

      // 解析 env 从多行文本到数组
      const envArray = formData.env
        .split('\n')
        .map(line => line.trim())
        .filter(line => line.length > 0);

      // 解析 host_path_mounts 从 JSON 文本到对象数组
      let hostPathMounts = undefined;
      if (formData.host_path_mounts.trim()) {
        try {
          hostPathMounts = JSON.parse(formData.host_path_mounts.trim());
        } catch (e) {
          console.error('Failed to parse host_path_mounts:', e);
        }
      }

      let lifecycle = undefined;
      if (formData.lifecycle.trim()) {
        try {
          lifecycle = JSON.parse(formData.lifecycle.trim());
        } catch (e) {
          console.error('Failed to parse lifecycle:', e);
          window.alert('Lifecycle must be valid JSON.');
          return;
        }
      }

      const updateData: UpdateTemplateRequest = {
        name: formData.name,
        image: formData.image,
        command: formData.command.trim() || undefined, // command 作为字符串
        env: envArray.length > 0 ? envArray : undefined,
        host_path_mounts: hostPathMounts,
        lifecycle,
        cpu_millicores: formData.cpu_millicores,
        cpu_request: formData.cpu_request,
        memory_mb: formData.memory_mb,
        memory_request: formData.memory_request,
        ttl_seconds: formData.ttl_seconds,
        metadata: Object.keys(metadata).length > 0 ? metadata : undefined,
      };

      await updateTemplate(selectedTemplate.id, updateData);
      setShowEditDialog(false);
      setSelectedTemplate(null);
      resetForm();
    } catch (err) {
      // Error handled by store
    } finally {
      setActionLoading(null);
    }
  };

  const handleDelete = async () => {
    if (!selectedTemplate) return;
    setActionLoading('delete');
    try {
      await deleteTemplate(selectedTemplate.id);
      setShowDeleteDialog(false);
      setSelectedTemplate(null);
    } catch (err) {
      // Error handled by store
    } finally {
      setActionLoading(null);
    }
  };

  const openCreateDialog = () => {
    resetForm();
    setShowCreateDialog(true);
  };

  const openEditDialog = (template: Template) => {
    setSelectedTemplate(template);
    setFormData({
      id: '',
      name: template.name,
      image: template.image,
      command: template.command || '', // command 直接作为字符串
      env: template.env ? template.env.join('\n') : '', // env 数组转为多行文本
      host_path_mounts: template.host_path_mounts ? JSON.stringify(template.host_path_mounts, null, 2) : '', // host_path_mounts 转为格式化 JSON
      lifecycle: template.lifecycle ? JSON.stringify(template.lifecycle, null, 2) : '',
      cpu_millicores: template.cpu_millicores,
      cpu_request: template.cpu_request,
      memory_mb: template.memory_mb,
      memory_request: template.memory_request,
      ttl_seconds: template.ttl_seconds,
      user_id: template.metadata?.user_id || '', // 从 metadata 中提取 user_id
      metadata: template.metadata || {},
    });
    setShowAdvanced(!!(template.cpu_request || template.memory_request));
    setShowEditDialog(true);
  };

  const openDeleteDialog = (template: Template) => {
    setSelectedTemplate(template);
    setShowDeleteDialog(true);
  };

  const resetForm = () => {
    setFormData({
      id: '',
      name: '',
      image: 'ubuntu:24.04',
      command: '', // Reset command
      env: '', // Reset env
      host_path_mounts: '', // Reset host_path_mounts
      lifecycle: '',
      cpu_millicores: 1000, // 默认 1 核 = 1000m
      cpu_request: undefined,
      memory_mb: 512,
      memory_request: undefined,
      ttl_seconds: undefined, // Reset ttl_seconds
      user_id: '', // Reset user_id
      metadata: {},
    });
    setShowAdvanced(false);
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">{t.template.list.title}</h1>
          <p className="text-muted-foreground mt-2">
            {t.template.list.subtitle}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            onClick={handleRefresh}
            disabled={actionLoading === 'refresh'}
          >
            <RefreshCw className={`mr-2 h-4 w-4 ${actionLoading === 'refresh' ? 'animate-spin' : ''}`} />
            {t.common.refresh}
          </Button>
          <Button onClick={openCreateDialog}>
            <Plus className="mr-2 h-4 w-4" />
            {t.template.list.createButton}
          </Button>
        </div>
      </div>

      {error && <ErrorAlert error={error} onDismiss={clearError} />}

      {/* Filter Section */}
      <Card>
        <CardHeader>
          <CardTitle>Filter Templates</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-end gap-2">
            <div className="flex-1">
              <Label htmlFor="user-id-filter">User ID</Label>
              <Input
                id="user-id-filter"
                placeholder="Filter by user ID (e.g., alice)"
                value={userIdFilter}
                onChange={(e) => setUserIdFilter(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleFilterByUserId()}
              />
            </div>
            <Button
              onClick={handleFilterByUserId}
              disabled={actionLoading === 'filter'}
            >
              {actionLoading === 'filter' ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Filter'}
            </Button>
            {userIdFilter && (
              <Button
                variant="outline"
                onClick={handleClearFilter}
                disabled={actionLoading === 'clear-filter'}
              >
                Clear
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t.template.list.allTemplates} ({templates?.length || 0})</CardTitle>
        </CardHeader>
        <CardContent>
          {loading && (!templates || templates.length === 0) ? (
            <div className="flex items-center justify-center p-12">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
          ) : !templates || templates.length === 0 ? (
            <div className="flex flex-col items-center justify-center p-12 text-center">
              <FileCode className="h-12 w-12 text-muted-foreground mx-auto mb-4 opacity-50" />
              <p className="text-muted-foreground mb-4">{t.template.list.noTemplates}</p>
              <Button onClick={openCreateDialog}>
                <Plus className="mr-2 h-4 w-4" />
                {t.template.list.createButton}
              </Button>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t.template.list.columns.id}</TableHead>
                  <TableHead>{t.template.list.columns.name}</TableHead>
                  <TableHead>{t.template.list.columns.image}</TableHead>
                  <TableHead>Command</TableHead>
                  <TableHead>User ID</TableHead>
                  <TableHead>{t.template.list.columns.resources}</TableHead>
                  <TableHead>{t.template.list.columns.createdAt}</TableHead>
                  <TableHead className="text-right">{t.common.actions}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {templates?.map((template) => (
                  <TableRow key={template.id}>
                    <TableCell className="font-mono text-sm">
                      {template.id}
                    </TableCell>
                    <TableCell className="font-medium">
                      <Link
                        to={`/templates/${template.id}`}
                        className="hover:underline text-primary"
                      >
                        {template.name}
                      </Link>
                    </TableCell>
                    <TableCell>
                      <code className="text-sm bg-muted px-2 py-1 rounded">
                        {template.image}
                      </code>
                    </TableCell>
                    <TableCell>
                      {template.command ? (
                        <code className="text-xs bg-muted px-2 py-1 rounded block max-w-xs truncate" title={template.command}>
                          {template.command}
                        </code>
                      ) : (
                        <span className="text-sm text-muted-foreground">-</span>
                      )}
                    </TableCell>
                    <TableCell>
                      {template.metadata?.user_id ? (
                        <span className="text-sm font-mono bg-primary/10 px-2 py-1 rounded">
                          {template.metadata.user_id}
                        </span>
                      ) : (
                        <span className="text-sm text-muted-foreground">-</span>
                      )}
                    </TableCell>
                    <TableCell>
                      <div className="text-sm space-y-1">
                        <div>
                          CPU: {template.cpu_request !== undefined && template.cpu_request !== template.cpu_millicores
                            ? `${(template.cpu_request / 1000).toFixed(1)}~${(template.cpu_millicores / 1000).toFixed(1)}c`
                            : `${(template.cpu_millicores / 1000).toFixed(1)}c`
                          }
                        </div>
                        <div>
                          Mem: {template.memory_request !== undefined && template.memory_request !== template.memory_mb
                            ? `${template.memory_request}~${template.memory_mb}MB`
                            : `${template.memory_mb}MB`
                          }
                        </div>
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-col">
                        <span className="text-sm">
                          {formatDistanceToNow(new Date(template.created_at), { addSuffix: true })}
                        </span>
                        <span className="text-xs text-muted-foreground">
                          {new Date(template.created_at).toLocaleString()}
                        </span>
                      </div>
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-2">
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => openEditDialog(template)}
                          title={t.template.list.editButton}
                        >
                          <Edit className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => openDeleteDialog(template)}
                          title={t.template.list.deleteButton}
                        >
                          <Trash2 className="h-4 w-4 text-destructive" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Create Dialog */}
      <Dialog open={showCreateDialog} onOpenChange={setShowCreateDialog}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t.template.create.title}</DialogTitle>
            <DialogDescription>
              {t.template.create.description}
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="create-id">Template ID (Optional)</Label>
              <Input
                id="create-id"
                value={formData.id}
                onChange={(e) => setFormData({ ...formData, id: e.target.value })}
                placeholder="Leave empty for auto-generated ID"
                disabled={actionLoading === 'create'}
              />
              <p className="text-xs text-muted-foreground">
                Custom ID for the template. If not provided, a random ID will be generated.
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="create-name">{t.template.create.nameLabel} *</Label>
              <Input
                id="create-name"
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                placeholder={t.template.create.namePlaceholder}
                disabled={actionLoading === 'create'}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="create-image">{t.template.create.imageLabel} *</Label>
              <Input
                id="create-image"
                value={formData.image}
                onChange={(e) => setFormData({ ...formData, image: e.target.value })}
                placeholder={t.template.create.imagePlaceholder}
                disabled={actionLoading === 'create'}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="create-user-id">User ID (Optional)</Label>
              <Input
                id="create-user-id"
                value={formData.user_id}
                onChange={(e) => setFormData({ ...formData, user_id: e.target.value })}
                placeholder="e.g., alice"
                disabled={actionLoading === 'create'}
              />
              <p className="text-xs text-muted-foreground">
                Specify the user ID to associate with this template (stored in metadata).
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="create-command">Container Command (Optional)</Label>
              <Input
                id="create-command"
                value={formData.command}
                onChange={(e) => setFormData({ ...formData, command: e.target.value })}
                placeholder='e.g., tail -f /dev/null'
                disabled={actionLoading === 'create'}
              />
              <p className="text-xs text-muted-foreground">
                Override container's default command (single string value).
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="create-env">Environment Variables (Optional)</Label>
              <Textarea
                id="create-env"
                value={formData.env}
                onChange={(e) => setFormData({ ...formData, env: e.target.value })}
                placeholder={'DATABASE_URL=postgresql://localhost:5432/mydb\nREDIS_URL=redis://localhost:6379\nAPI_KEY=sk-test-xxxxx\nDEBUG=true\nPORT=8080'}
                rows={6}
                disabled={actionLoading === 'create'}
              />
              <p className="text-xs text-muted-foreground">
                Enter environment variables in KEY=VALUE format, one per line.
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="create-host-path-mounts">Host Path Mounts (Optional)</Label>
              <Textarea
                id="create-host-path-mounts"
                value={formData.host_path_mounts}
                onChange={(e) => setFormData({ ...formData, host_path_mounts: e.target.value })}
                placeholder={'[\n  {\n    "host_path": "/data/models",\n    "container_path": "/workspace/models",\n    "read_only": false\n  },\n  {\n    "host_path": "/data/datasets",\n    "container_path": "/workspace/datasets",\n    "read_only": true\n  }\n]'}
                rows={10}
                disabled={actionLoading === 'create'}
              />
              <p className="text-xs text-muted-foreground">
                Enter host path mounts in JSON array format. Each mount has host_path, container_path, and read_only fields.
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="create-lifecycle">Lifecycle Hooks (Optional)</Label>
              <Textarea
                id="create-lifecycle"
                value={formData.lifecycle}
                onChange={(e) => setFormData({ ...formData, lifecycle: e.target.value })}
                placeholder={'{\n  "postStart": {\n    "exec": { "command": ["/bin/sh", "-lc", "echo started"] }\n  },\n  "preStop": {\n    "exec": { "command": ["/bin/sh", "-lc", "echo stopping"] },\n    "terminationGracePeriodSeconds": 30\n  }\n}'}
                rows={10}
                disabled={actionLoading === 'create'}
              />
              <p className="text-xs text-muted-foreground">
                Enter lifecycle hooks in JSON format. Supports postStart.exec.command and preStop.exec.command with terminationGracePeriodSeconds.
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="create-ttl">TTL (Time To Live) - Seconds (Optional)</Label>
              <Input
                id="create-ttl"
                type="number"
                min="300"
                max="86400"
                value={formData.ttl_seconds || ''}
                onChange={(e) => setFormData({
                  ...formData,
                  ttl_seconds: e.target.value ? parseInt(e.target.value) : undefined
                })}
                placeholder="e.g., 3600 (1 hour)"
                disabled={actionLoading === 'create'}
              />
              <p className="text-xs text-muted-foreground">
                Sandbox lifetime in seconds. Range: 300 (5 min) to 86400 (24 hours). Leave empty for default.
              </p>
            </div>

            <div className="grid grid-cols-3 gap-4">
              <div className="space-y-2">
                <Label htmlFor="create-cpu">CPU Limits (millicores) *</Label>
                <Input
                  id="create-cpu"
                  type="number"
                  min="100"
                  max="128000"
                  step="100"
                  value={formData.cpu_millicores}
                  onChange={(e) => setFormData({ ...formData, cpu_millicores: parseInt(e.target.value) || 100 })}
                  disabled={actionLoading === 'create'}
                />
                <p className="text-xs text-muted-foreground">
                  1000m = 1 core
                </p>
              </div>
              <div className="space-y-2">
                <Label htmlFor="create-memory">Memory Limits (MB) *</Label>
                <Input
                  id="create-memory"
                  type="number"
                  min="128"
                  max="131072"
                  value={formData.memory_mb}
                  onChange={(e) => setFormData({ ...formData, memory_mb: parseInt(e.target.value) || 128 })}
                  disabled={actionLoading === 'create'}
                />
              </div>
            </div>

            {/* Advanced Settings Toggle */}
            <div className="border-t pt-4">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setShowAdvanced(!showAdvanced)}
                disabled={actionLoading === 'create'}
              >
                {showAdvanced ? '− Hide' : '+ Show'} Advanced Settings (Resource Requests)
              </Button>
            </div>

            {/* Advanced Resource Settings */}
            {showAdvanced && (
              <div className="space-y-4 p-4 border rounded-lg bg-muted/30">
                <p className="text-sm text-muted-foreground">
                  Configure resource requests for oversubscription. Leave empty to use limits (no oversubscription).
                </p>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="create-cpu-request">CPU Requests (millicores)</Label>
                    <Input
                      id="create-cpu-request"
                      type="number"
                      min="100"
                      max={formData.cpu_millicores}
                      step="100"
                      placeholder={`Default: ${formData.cpu_millicores}m`}
                      value={formData.cpu_request || ''}
                      onChange={(e) => setFormData({
                        ...formData,
                        cpu_request: e.target.value ? parseInt(e.target.value) : undefined
                      })}
                      disabled={actionLoading === 'create'}
                    />
                    <p className="text-xs text-muted-foreground">
                      Must be ≤ {formData.cpu_millicores}m (limits)
                    </p>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="create-memory-request">Memory Requests (MB)</Label>
                    <Input
                      id="create-memory-request"
                      type="number"
                      min="128"
                      max={formData.memory_mb}
                      placeholder={`Default: ${formData.memory_mb}`}
                      value={formData.memory_request || ''}
                      onChange={(e) => setFormData({
                        ...formData,
                        memory_request: e.target.value ? parseInt(e.target.value) : undefined
                      })}
                      disabled={actionLoading === 'create'}
                    />
                    <p className="text-xs text-muted-foreground">
                      Must be ≤ {formData.memory_mb} (limits)
                    </p>
                  </div>
                </div>
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowCreateDialog(false)} disabled={actionLoading === 'create'}>
              {t.common.cancel}
            </Button>
            <Button onClick={handleCreate} disabled={actionLoading === 'create' || !formData.name.trim() || !formData.image.trim()}>
              {actionLoading === 'create' ? t.template.create.creating : t.common.create}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Edit Dialog */}
      <Dialog open={showEditDialog} onOpenChange={setShowEditDialog}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t.template.edit.title}</DialogTitle>
            <DialogDescription>
              {t.template.edit.description}
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="space-y-2">
              <Label>{t.template.edit.idLabel}</Label>
              <Input value={selectedTemplate?.id || ''} disabled className="bg-muted font-mono" />
            </div>

            <div className="space-y-2">
              <Label htmlFor="edit-name">{t.template.edit.nameLabel} *</Label>
              <Input
                id="edit-name"
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                disabled={actionLoading === 'edit'}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="edit-image">{t.template.edit.imageLabel} *</Label>
              <Input
                id="edit-image"
                value={formData.image}
                onChange={(e) => setFormData({ ...formData, image: e.target.value })}
                disabled={actionLoading === 'edit'}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="edit-user-id">User ID (Optional)</Label>
              <Input
                id="edit-user-id"
                value={formData.user_id}
                onChange={(e) => setFormData({ ...formData, user_id: e.target.value })}
                placeholder="e.g., alice"
                disabled={actionLoading === 'edit'}
              />
              <p className="text-xs text-muted-foreground">
                Specify the user ID to associate with this template (stored in metadata).
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="edit-command">Container Command (Optional)</Label>
              <Input
                id="edit-command"
                value={formData.command}
                onChange={(e) => setFormData({ ...formData, command: e.target.value })}
                placeholder='e.g., tail -f /dev/null'
                disabled={actionLoading === 'edit'}
              />
              <p className="text-xs text-muted-foreground">
                Override container's default command (single string value).
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="edit-env">Environment Variables (Optional)</Label>
              <Textarea
                id="edit-env"
                value={formData.env}
                onChange={(e) => setFormData({ ...formData, env: e.target.value })}
                placeholder={'DATABASE_URL=postgresql://localhost:5432/mydb\nREDIS_URL=redis://localhost:6379\nAPI_KEY=sk-test-xxxxx\nDEBUG=true\nPORT=8080'}
                rows={6}
                disabled={actionLoading === 'edit'}
              />
              <p className="text-xs text-muted-foreground">
                Enter environment variables in KEY=VALUE format, one per line.
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="edit-host-path-mounts">Host Path Mounts (Optional)</Label>
              <Textarea
                id="edit-host-path-mounts"
                value={formData.host_path_mounts}
                onChange={(e) => setFormData({ ...formData, host_path_mounts: e.target.value })}
                placeholder={'[\n  {\n    "host_path": "/data/models",\n    "container_path": "/workspace/models",\n    "read_only": false\n  },\n  {\n    "host_path": "/data/datasets",\n    "container_path": "/workspace/datasets",\n    "read_only": true\n  }\n]'}
                rows={10}
                disabled={actionLoading === 'edit'}
              />
              <p className="text-xs text-muted-foreground">
                Enter host path mounts in JSON array format. Each mount has host_path, container_path, and read_only fields.
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="edit-lifecycle">Lifecycle Hooks (Optional)</Label>
              <Textarea
                id="edit-lifecycle"
                value={formData.lifecycle}
                onChange={(e) => setFormData({ ...formData, lifecycle: e.target.value })}
                placeholder={'{\n  "postStart": {\n    "exec": { "command": ["/bin/sh", "-lc", "echo started"] }\n  },\n  "preStop": {\n    "exec": { "command": ["/bin/sh", "-lc", "echo stopping"] },\n    "terminationGracePeriodSeconds": 30\n  }\n}'}
                rows={10}
                disabled={actionLoading === 'edit'}
              />
              <p className="text-xs text-muted-foreground">
                Enter lifecycle hooks in JSON format. Supports postStart.exec.command and preStop.exec.command with terminationGracePeriodSeconds.
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="edit-ttl">TTL (Time To Live) - Seconds (Optional)</Label>
              <Input
                id="edit-ttl"
                type="number"
                min="300"
                max="86400"
                value={formData.ttl_seconds || ''}
                onChange={(e) => setFormData({
                  ...formData,
                  ttl_seconds: e.target.value ? parseInt(e.target.value) : undefined
                })}
                placeholder="e.g., 3600 (1 hour)"
                disabled={actionLoading === 'edit'}
              />
              <p className="text-xs text-muted-foreground">
                Sandbox lifetime in seconds. Range: 300 (5 min) to 86400 (24 hours). Leave empty for default.
              </p>
            </div>

            <div className="grid grid-cols-3 gap-4">
              <div className="space-y-2">
                <Label htmlFor="edit-cpu">CPU Limits (millicores) *</Label>
                <Input
                  id="edit-cpu"
                  type="number"
                  min="100"
                  max="128000"
                  step="100"
                  value={formData.cpu_millicores}
                  onChange={(e) => setFormData({ ...formData, cpu_millicores: parseInt(e.target.value) || 100 })}
                  disabled={actionLoading === 'edit'}
                />
                <p className="text-xs text-muted-foreground">
                  1000m = 1 core
                </p>
              </div>
              <div className="space-y-2">
                <Label htmlFor="edit-memory">Memory Limits (MB) *</Label>
                <Input
                  id="edit-memory"
                  type="number"
                  min="128"
                  max="131072"
                  value={formData.memory_mb}
                  onChange={(e) => setFormData({ ...formData, memory_mb: parseInt(e.target.value) || 128 })}
                  disabled={actionLoading === 'edit'}
                />
              </div>
            </div>

            {/* Advanced Settings Toggle */}
            <div className="border-t pt-4">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setShowAdvanced(!showAdvanced)}
                disabled={actionLoading === 'edit'}
              >
                {showAdvanced ? '− Hide' : '+ Show'} Advanced Settings (Resource Requests)
              </Button>
            </div>

            {/* Advanced Resource Settings */}
            {showAdvanced && (
              <div className="space-y-4 p-4 border rounded-lg bg-muted/30">
                <p className="text-sm text-muted-foreground">
                  Configure resource requests for oversubscription. Leave empty to use limits (no oversubscription).
                </p>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="edit-cpu-request">CPU Requests (millicores)</Label>
                    <Input
                      id="edit-cpu-request"
                      type="number"
                      min="100"
                      max={formData.cpu_millicores}
                      step="100"
                      placeholder={`Default: ${formData.cpu_millicores}m`}
                      value={formData.cpu_request || ''}
                      onChange={(e) => setFormData({
                        ...formData,
                        cpu_request: e.target.value ? parseInt(e.target.value) : undefined
                      })}
                      disabled={actionLoading === 'edit'}
                    />
                    <p className="text-xs text-muted-foreground">
                      Must be ≤ {formData.cpu_millicores}m (limits)
                    </p>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="edit-memory-request">Memory Requests (MB)</Label>
                    <Input
                      id="edit-memory-request"
                      type="number"
                      min="128"
                      max={formData.memory_mb}
                      placeholder={`Default: ${formData.memory_mb}`}
                      value={formData.memory_request || ''}
                      onChange={(e) => setFormData({
                        ...formData,
                        memory_request: e.target.value ? parseInt(e.target.value) : undefined
                      })}
                      disabled={actionLoading === 'edit'}
                    />
                    <p className="text-xs text-muted-foreground">
                      Must be ≤ {formData.memory_mb} (limits)
                    </p>
                  </div>
                </div>
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowEditDialog(false)} disabled={actionLoading === 'edit'}>
              {t.common.cancel}
            </Button>
            <Button onClick={handleEdit} disabled={actionLoading === 'edit' || !formData.name.trim() || !formData.image.trim()}>
              {actionLoading === 'edit' ? t.template.edit.updating : t.common.update}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Dialog */}
      <AlertDialog open={showDeleteDialog} onOpenChange={setShowDeleteDialog}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t.template.delete.title}</AlertDialogTitle>
            <AlertDialogDescription>
              {t.template.delete.description}
              <br />
              <br />
              <span className="font-mono text-sm">
                {selectedTemplate?.id} - {selectedTemplate?.name}
              </span>
              <br />
              <br />
              <strong>{t.template.delete.note}</strong> {t.template.delete.noteText}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t.common.cancel}</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDelete}
              className="bg-destructive text-destructive-foreground"
              disabled={actionLoading === 'delete'}
            >
              {actionLoading === 'delete' ? t.template.delete.deleting : t.template.delete.confirm}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
