import { useEffect, useState } from 'react';
import { useSandboxStore } from '@/store/sandboxStore';
import { useApp } from '@/contexts/AppContext';
import type { Webhook, CreateWebhookRequest, UpdateWebhookRequest, WebhookEvent } from '@/types/sandbox';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Checkbox } from '@/components/ui/checkbox';
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
import { Plus, Edit, Trash2, RefreshCw, Loader2, Webhook as WebhookIcon, ChevronDown, ChevronRight, Copy, Check } from 'lucide-react';
import { formatDistanceToNow } from 'date-fns';
import { Badge } from '@/components/ui/badge';

const WEBHOOK_EVENTS: WebhookEvent[] = ['sandbox_started', 'sandbox_ready', 'sandbox_deleted'];

// ── Payload 示例数据 ──────────────────────────────────────────────

const SANDBOX_EXAMPLE = {
  id: "sb-a1b2c3d4",
  name: "my-sandbox",
  template_id: "ubuntu-22.04",
  image: "ubuntu:22.04",
  cpu_millicores: 1000,
  memory_mb: 2048,
  status: "running",
  terminating: false,
  pool_state: "allocated",
  workspace_path: "/workspace",
  metadata: { user_id: "user-xyz", project: "demo" },
  allocated_at: "2024-01-15T10:00:00Z",
  created_at: "2024-01-15T09:59:45Z",
  updated_at: "2024-01-15T10:00:02Z",
  ttl_seconds: 3600,
  expires_at: "2024-01-15T11:00:00Z",
  time_remaining_seconds: 3598,
};

const TEMPLATE_EXAMPLE = {
  id: "ubuntu-22.04",
  name: "Ubuntu 22.04",
  description: "Standard Ubuntu environment",
  image: "ubuntu:22.04",
  command: "/bin/bash",
  env: ["HOME=/root", "LANG=en_US.UTF-8"],
  cpu_millicores: 1000,
  memory_mb: 2048,
  ttl_seconds: 3600,
  metadata: {},
  created_at: "2024-01-01T00:00:00Z",
  updated_at: "2024-01-01T00:00:00Z",
};

const K8S_EXAMPLE = {
  namespace: "litterbox",
  pod_name: "sb-a1b2c3d4-5f6g7h",
  pod_ip: "10.244.1.42",
  node_name: "node-worker-1",
  container_name: "main",
};

const PAYLOAD_EXAMPLES: Record<WebhookEvent, object> = {
  sandbox_started: {
    event_id: "ev-x1y2z3",
    event_type: "sandbox_started",
    occurred_at: "2024-01-15T09:59:45Z",
    deletion_reason: "",
    sandbox: { ...SANDBOX_EXAMPLE, status: "created" },
    template: TEMPLATE_EXAMPLE,
    kubernetes: { ...K8S_EXAMPLE, pod_name: "", pod_ip: "", node_name: "", container_name: "" },
  },
  sandbox_ready: {
    event_id: "ev-a4b5c6",
    event_type: "sandbox_ready",
    occurred_at: "2024-01-15T10:00:02Z",
    deletion_reason: "",
    sandbox: SANDBOX_EXAMPLE,
    template: TEMPLATE_EXAMPLE,
    kubernetes: K8S_EXAMPLE,
  },
  sandbox_deleted: {
    event_id: "ev-d7e8f9",
    event_type: "sandbox_deleted",
    occurred_at: "2024-01-15T10:30:00Z",
    deletion_reason: "ttl_expired",
    sandbox: { ...SANDBOX_EXAMPLE, status: "stopped", terminating: true, time_remaining_seconds: 0 },
    template: TEMPLATE_EXAMPLE,
    kubernetes: K8S_EXAMPLE,
  },
};

const EVENT_LABELS: Record<WebhookEvent, string> = {
  sandbox_started: "sandbox_started",
  sandbox_ready: "sandbox_ready",
  sandbox_deleted: "sandbox_deleted",
};

const EVENT_DESCRIPTIONS: Record<WebhookEvent, string> = {
  sandbox_started: "Fired when sandbox creation is initiated (pod scheduling begins).",
  sandbox_ready: "Fired when the sandbox pod is Running and passes the readiness check.",
  sandbox_deleted: "Fired when a sandbox is fully deleted. deletion_reason: \"manual\" | \"ttl_expired\" | \"reconcile\".",
};

function PayloadExamples() {
  const [open, setOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<WebhookEvent>('sandbox_ready');
  const [copied, setCopied] = useState(false);

  const payload = PAYLOAD_EXAMPLES[activeTab];
  const json = JSON.stringify(payload, null, 2);

  const handleCopy = () => {
    navigator.clipboard.writeText(json);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <Card>
      <CardHeader
        className="cursor-pointer select-none"
        onClick={() => setOpen((v) => !v)}
      >
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
              Payload Examples
            </CardTitle>
            <CardDescription className="mt-1">
              Example request body sent to your webhook endpoint for each event type.
            </CardDescription>
          </div>
        </div>
      </CardHeader>

      {open && (
        <CardContent className="space-y-4">
          {/* Delivery details */}
          <div className="rounded-lg border bg-muted/40 p-4 space-y-2 text-sm">
            <p className="font-medium">Delivery details</p>
            <ul className="space-y-1 text-muted-foreground list-disc list-inside">
              <li>Method: <code className="text-foreground font-mono">POST</code></li>
              <li>Content-Type: <code className="text-foreground font-mono">application/json</code></li>
              <li>
                Authorization header (if token set):{' '}
                <code className="text-foreground font-mono">Authorization: Bearer &lt;token&gt;</code>
              </li>
              <li>
                Success: any <code className="text-foreground font-mono">2xx</code> response.
                Non-2xx triggers retry up to <em>max_attempts</em> times.
              </li>
            </ul>
          </div>

          {/* Event tabs */}
          <div>
            <div className="flex gap-1 border-b mb-4">
              {WEBHOOK_EVENTS.map((ev) => (
                <button
                  key={ev}
                  onClick={() => setActiveTab(ev)}
                  className={`px-3 py-2 text-sm font-medium transition-colors border-b-2 -mb-px ${
                    activeTab === ev
                      ? 'border-primary text-primary'
                      : 'border-transparent text-muted-foreground hover:text-foreground'
                  }`}
                >
                  {EVENT_LABELS[ev]}
                </button>
              ))}
            </div>

            <p className="text-sm text-muted-foreground mb-3">{EVENT_DESCRIPTIONS[activeTab]}</p>

            <div className="relative">
              <Button
                size="sm"
                variant="outline"
                className="absolute top-2 right-2 h-7 gap-1 text-xs z-10"
                onClick={handleCopy}
              >
                {copied
                  ? <><Check className="h-3 w-3" /> Copied</>
                  : <><Copy className="h-3 w-3" /> Copy</>
                }
              </Button>
              <pre className="bg-muted rounded-lg p-4 text-xs font-mono overflow-x-auto leading-relaxed">
                {json}
              </pre>
            </div>
          </div>
        </CardContent>
      )}
    </Card>
  );
}

export function Webhooks() {
  const { t } = useApp();
  const {
    webhooks,
    fetchWebhooks,
    createWebhook,
    updateWebhook,
    deleteWebhook,
    webhooksLoading,
    error,
    clearError
  } = useSandboxStore();

  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [showEditDialog, setShowEditDialog] = useState(false);
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const [selectedWebhook, setSelectedWebhook] = useState<Webhook | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  // Filter state
  const [userIdFilter, setUserIdFilter] = useState('');

  const [formData, setFormData] = useState<{
    name: string;
    user_id: string;
    url: string;
    token: string;
    template_ids: string;
    events: WebhookEvent[];
    enabled: boolean;
    retry: {
      max_attempts: number;
      interval_ms: number;
      timeout_ms: number;
    };
  }>({
    name: '',
    user_id: '',
    url: '',
    token: '',
    template_ids: '',
    events: ['sandbox_ready'],
    enabled: true,
    retry: {
      max_attempts: 5,
      interval_ms: 200,
      timeout_ms: 1000,
    },
  });

  const [showAdvanced, setShowAdvanced] = useState(false);

  useEffect(() => {
    fetchWebhooks();
  }, [fetchWebhooks]);

  const handleRefresh = () => {
    setActionLoading('refresh');
    fetchWebhooks(userIdFilter ? { user_id: userIdFilter } : undefined);
    setTimeout(() => setActionLoading(null), 500);
  };

  const handleFilterByUserId = () => {
    setActionLoading('filter');
    fetchWebhooks(userIdFilter ? { user_id: userIdFilter } : undefined);
    setTimeout(() => setActionLoading(null), 500);
  };

  const handleClearFilter = () => {
    setUserIdFilter('');
    setActionLoading('clear-filter');
    fetchWebhooks();
    setTimeout(() => setActionLoading(null), 500);
  };

  const resetForm = () => {
    setFormData({
      name: '',
      user_id: '',
      url: '',
      token: '',
      template_ids: '',
      events: ['sandbox_ready'],
      enabled: true,
      retry: {
        max_attempts: 5,
        interval_ms: 200,
        timeout_ms: 1000,
      },
    });
    setShowAdvanced(false);
  };

  const handleCreate = async () => {
    setActionLoading('create');
    try {
      const templateIdsArray = formData.template_ids
        .split(',')
        .map(id => id.trim())
        .filter(id => id.length > 0);

      await createWebhook({
        name: formData.name,
        user_id: formData.user_id,
        url: formData.url,
        token: formData.token,
        template_ids: templateIdsArray,
        events: formData.events,
        enabled: formData.enabled,
        retry: formData.retry,
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
    if (!selectedWebhook) return;
    setActionLoading('edit');
    try {
      const templateIdsArray = formData.template_ids
        .split(',')
        .map(id => id.trim())
        .filter(id => id.length > 0);

      await updateWebhook(selectedWebhook.id, {
        name: formData.name,
        url: formData.url,
        token: formData.token,
        template_ids: templateIdsArray,
        events: formData.events,
        enabled: formData.enabled,
        retry: formData.retry,
      });
      setShowEditDialog(false);
      setSelectedWebhook(null);
      resetForm();
    } catch (err) {
      // Error handled by store
    } finally {
      setActionLoading(null);
    }
  };

  const handleDelete = async () => {
    if (!selectedWebhook) return;
    setActionLoading('delete');
    try {
      await deleteWebhook(selectedWebhook.id);
      setShowDeleteDialog(false);
      setSelectedWebhook(null);
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

  const openEditDialog = (webhook: Webhook) => {
    setSelectedWebhook(webhook);
    setFormData({
      name: webhook.name,
      user_id: webhook.user_id,
      url: webhook.url,
      token: webhook.token,
      template_ids: webhook.template_ids.join(', '),
      events: webhook.events,
      enabled: webhook.enabled,
      retry: webhook.retry,
    });
    setShowEditDialog(true);
  };

  const openDeleteDialog = (webhook: Webhook) => {
    setSelectedWebhook(webhook);
    setShowDeleteDialog(true);
  };

  const toggleEvent = (event: WebhookEvent) => {
    setFormData(prev => ({
      ...prev,
      events: prev.events.includes(event)
        ? prev.events.filter(e => e !== event)
        : [...prev.events, event],
    }));
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight flex items-center gap-2">
            <WebhookIcon className="h-8 w-8 text-primary" />
            {t.webhook.list.title}
          </h1>
          <p className="text-muted-foreground mt-2">{t.webhook.list.description}</p>
        </div>
        <div className="flex items-center gap-2">
          <Button onClick={handleRefresh} variant="outline" disabled={webhooksLoading || actionLoading === 'refresh'}>
            {actionLoading === 'refresh' ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
            <span className="ml-2">{t.common.refresh}</span>
          </Button>
          <Button onClick={openCreateDialog}>
            <Plus className="h-4 w-4" />
            <span className="ml-2">{t.webhook.list.createButton}</span>
          </Button>
        </div>
      </div>

      {/* Filters */}
      <Card>
        <CardHeader>
          <CardTitle>Filter</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-end gap-4">
            <div className="flex-1">
              <Label htmlFor="user-id-filter">User ID</Label>
              <Input
                id="user-id-filter"
                placeholder="Filter by user ID"
                value={userIdFilter}
                onChange={(e) => setUserIdFilter(e.target.value)}
              />
            </div>
            <Button onClick={handleFilterByUserId} disabled={actionLoading === 'filter'}>
              {actionLoading === 'filter' && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
              Apply Filter
            </Button>
            {userIdFilter && (
              <Button onClick={handleClearFilter} variant="outline" disabled={actionLoading === 'clear-filter'}>
                Clear Filter
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Error Alert */}
      {error && <ErrorAlert error={error} onDismiss={clearError} />}

      {/* Webhooks Table */}
      <Card>
        <CardHeader>
          <CardTitle>{t.webhook.list.title}</CardTitle>
        </CardHeader>
        <CardContent>
          {webhooksLoading && webhooks.length === 0 ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
          ) : webhooks.length === 0 ? (
            <div className="text-center py-12">
              <WebhookIcon className="mx-auto h-12 w-12 text-muted-foreground/50" />
              <p className="mt-4 text-muted-foreground">{t.webhook.list.noWebhooks}</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t.webhook.list.columns.name}</TableHead>
                    <TableHead>{t.webhook.list.columns.url}</TableHead>
                    <TableHead>{t.webhook.list.columns.events}</TableHead>
                    <TableHead>{t.webhook.list.columns.templates}</TableHead>
                    <TableHead>{t.webhook.list.columns.enabled}</TableHead>
                    <TableHead>{t.webhook.list.columns.createdAt}</TableHead>
                    <TableHead className="text-right">{t.webhook.list.columns.actions}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {webhooks.map((webhook) => (
                    <TableRow key={webhook.id}>
                      <TableCell className="font-medium">{webhook.name}</TableCell>
                      <TableCell className="max-w-xs truncate text-xs text-muted-foreground">
                        {webhook.url}
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap gap-1">
                          {webhook.events.map((event) => (
                            <Badge key={event} variant="secondary" className="text-xs">
                              {t.webhook.events[event]}
                            </Badge>
                          ))}
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline">{webhook.template_ids.length} templates</Badge>
                      </TableCell>
                      <TableCell>
                        <Badge variant={webhook.enabled ? 'default' : 'secondary'}>
                          {webhook.enabled ? t.webhook.status.enabled : t.webhook.status.disabled}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-muted-foreground text-sm">
                        {formatDistanceToNow(new Date(webhook.created_at), { addSuffix: true })}
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex justify-end gap-2">
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => openEditDialog(webhook)}
                          >
                            <Edit className="h-3 w-3" />
                            <span className="ml-1">{t.webhook.list.editButton}</span>
                          </Button>
                          <Button
                            size="sm"
                            variant="destructive"
                            onClick={() => openDeleteDialog(webhook)}
                          >
                            <Trash2 className="h-3 w-3" />
                            <span className="ml-1">{t.webhook.list.deleteButton}</span>
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Create Dialog */}
      <Dialog open={showCreateDialog} onOpenChange={setShowCreateDialog}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t.webhook.create.title}</DialogTitle>
            <DialogDescription>{t.webhook.create.description}</DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="name">{t.webhook.create.nameLabel}</Label>
                <Input
                  id="name"
                  placeholder={t.webhook.create.namePlaceholder}
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="user_id">{t.webhook.create.userIdLabel}</Label>
                <Input
                  id="user_id"
                  placeholder={t.webhook.create.userIdPlaceholder}
                  value={formData.user_id}
                  onChange={(e) => setFormData({ ...formData, user_id: e.target.value })}
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="url">{t.webhook.create.urlLabel}</Label>
              <Input
                id="url"
                placeholder={t.webhook.create.urlPlaceholder}
                value={formData.url}
                onChange={(e) => setFormData({ ...formData, url: e.target.value })}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="token">{t.webhook.create.tokenLabel}</Label>
              <Input
                id="token"
                type="password"
                placeholder={t.webhook.create.tokenPlaceholder}
                value={formData.token}
                onChange={(e) => setFormData({ ...formData, token: e.target.value })}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="template_ids">{t.webhook.create.templatesLabel}</Label>
              <Input
                id="template_ids"
                placeholder={t.webhook.create.templatesPlaceholder}
                value={formData.template_ids}
                onChange={(e) => setFormData({ ...formData, template_ids: e.target.value })}
              />
            </div>

            <div className="space-y-2">
              <Label>{t.webhook.create.eventsLabel}</Label>
              <div className="flex flex-col space-y-2">
                {WEBHOOK_EVENTS.map((event) => (
                  <div key={event} className="flex items-center space-x-2">
                    <Checkbox
                      id={event}
                      checked={formData.events.includes(event)}
                      onCheckedChange={() => toggleEvent(event)}
                    />
                    <label
                      htmlFor={event}
                      className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70"
                    >
                      {t.webhook.events[event]}
                    </label>
                  </div>
                ))}
              </div>
            </div>

            <div className="flex items-center space-x-2">
              <Switch
                id="enabled"
                checked={formData.enabled}
                onCheckedChange={(checked) => setFormData({ ...formData, enabled: checked })}
              />
              <Label htmlFor="enabled">{t.webhook.create.enabledLabel}</Label>
            </div>

            {/* Advanced Settings */}
            <div>
              <Button
                type="button"
                variant="ghost"
                onClick={() => setShowAdvanced(!showAdvanced)}
                className="px-0"
              >
                {showAdvanced ? '▼' : '▶'} {t.webhook.create.retryLabel}
              </Button>
              {showAdvanced && (
                <div className="grid grid-cols-3 gap-4 mt-4">
                  <div className="space-y-2">
                    <Label htmlFor="max_attempts">{t.webhook.create.maxAttemptsLabel}</Label>
                    <Input
                      id="max_attempts"
                      type="number"
                      min="1"
                      max="10"
                      value={formData.retry.max_attempts}
                      onChange={(e) =>
                        setFormData({
                          ...formData,
                          retry: { ...formData.retry, max_attempts: parseInt(e.target.value) || 5 },
                        })
                      }
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="interval_ms">{t.webhook.create.intervalMsLabel}</Label>
                    <Input
                      id="interval_ms"
                      type="number"
                      min="100"
                      max="10000"
                      value={formData.retry.interval_ms}
                      onChange={(e) =>
                        setFormData({
                          ...formData,
                          retry: { ...formData.retry, interval_ms: parseInt(e.target.value) || 200 },
                        })
                      }
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="timeout_ms">{t.webhook.create.timeoutMsLabel}</Label>
                    <Input
                      id="timeout_ms"
                      type="number"
                      min="500"
                      max="30000"
                      value={formData.retry.timeout_ms}
                      onChange={(e) =>
                        setFormData({
                          ...formData,
                          retry: { ...formData.retry, timeout_ms: parseInt(e.target.value) || 1000 },
                        })
                      }
                    />
                  </div>
                </div>
              )}
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setShowCreateDialog(false)}>
              {t.common.cancel}
            </Button>
            <Button onClick={handleCreate} disabled={actionLoading === 'create'}>
              {actionLoading === 'create' && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
              {actionLoading === 'create' ? t.webhook.create.creating : t.common.create}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Edit Dialog */}
      <Dialog open={showEditDialog} onOpenChange={setShowEditDialog}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t.webhook.edit.title}</DialogTitle>
            <DialogDescription>{t.webhook.edit.description}</DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="edit-name">{t.webhook.create.nameLabel}</Label>
              <Input
                id="edit-name"
                placeholder={t.webhook.create.namePlaceholder}
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="edit-url">{t.webhook.create.urlLabel}</Label>
              <Input
                id="edit-url"
                placeholder={t.webhook.create.urlPlaceholder}
                value={formData.url}
                onChange={(e) => setFormData({ ...formData, url: e.target.value })}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="edit-token">{t.webhook.create.tokenLabel}</Label>
              <Input
                id="edit-token"
                type="password"
                placeholder={t.webhook.create.tokenPlaceholder}
                value={formData.token}
                onChange={(e) => setFormData({ ...formData, token: e.target.value })}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="edit-template_ids">{t.webhook.create.templatesLabel}</Label>
              <Input
                id="edit-template_ids"
                placeholder={t.webhook.create.templatesPlaceholder}
                value={formData.template_ids}
                onChange={(e) => setFormData({ ...formData, template_ids: e.target.value })}
              />
            </div>

            <div className="space-y-2">
              <Label>{t.webhook.create.eventsLabel}</Label>
              <div className="flex flex-col space-y-2">
                {WEBHOOK_EVENTS.map((event) => (
                  <div key={event} className="flex items-center space-x-2">
                    <Checkbox
                      id={`edit-${event}`}
                      checked={formData.events.includes(event)}
                      onCheckedChange={() => toggleEvent(event)}
                    />
                    <label
                      htmlFor={`edit-${event}`}
                      className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70"
                    >
                      {t.webhook.events[event]}
                    </label>
                  </div>
                ))}
              </div>
            </div>

            <div className="flex items-center space-x-2">
              <Switch
                id="edit-enabled"
                checked={formData.enabled}
                onCheckedChange={(checked) => setFormData({ ...formData, enabled: checked })}
              />
              <Label htmlFor="edit-enabled">{t.webhook.create.enabledLabel}</Label>
            </div>

            {/* Advanced Settings */}
            <div>
              <Button
                type="button"
                variant="ghost"
                onClick={() => setShowAdvanced(!showAdvanced)}
                className="px-0"
              >
                {showAdvanced ? '▼' : '▶'} {t.webhook.create.retryLabel}
              </Button>
              {showAdvanced && (
                <div className="grid grid-cols-3 gap-4 mt-4">
                  <div className="space-y-2">
                    <Label htmlFor="edit-max_attempts">{t.webhook.create.maxAttemptsLabel}</Label>
                    <Input
                      id="edit-max_attempts"
                      type="number"
                      min="1"
                      max="10"
                      value={formData.retry.max_attempts}
                      onChange={(e) =>
                        setFormData({
                          ...formData,
                          retry: { ...formData.retry, max_attempts: parseInt(e.target.value) || 5 },
                        })
                      }
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="edit-interval_ms">{t.webhook.create.intervalMsLabel}</Label>
                    <Input
                      id="edit-interval_ms"
                      type="number"
                      min="100"
                      max="10000"
                      value={formData.retry.interval_ms}
                      onChange={(e) =>
                        setFormData({
                          ...formData,
                          retry: { ...formData.retry, interval_ms: parseInt(e.target.value) || 200 },
                        })
                      }
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="edit-timeout_ms">{t.webhook.create.timeoutMsLabel}</Label>
                    <Input
                      id="edit-timeout_ms"
                      type="number"
                      min="500"
                      max="30000"
                      value={formData.retry.timeout_ms}
                      onChange={(e) =>
                        setFormData({
                          ...formData,
                          retry: { ...formData.retry, timeout_ms: parseInt(e.target.value) || 1000 },
                        })
                      }
                    />
                  </div>
                </div>
              )}
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setShowEditDialog(false)}>
              {t.common.cancel}
            </Button>
            <Button onClick={handleEdit} disabled={actionLoading === 'edit'}>
              {actionLoading === 'edit' && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
              {actionLoading === 'edit' ? t.webhook.edit.updating : t.common.update}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <AlertDialog open={showDeleteDialog} onOpenChange={setShowDeleteDialog}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t.webhook.delete.title}</AlertDialogTitle>
            <AlertDialogDescription>
              {t.webhook.delete.description}
              {selectedWebhook && (
                <div className="mt-2 p-2 bg-muted rounded text-sm">
                  <strong>{selectedWebhook.name}</strong>
                </div>
              )}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t.common.cancel}</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDelete}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              disabled={actionLoading === 'delete'}
            >
              {actionLoading === 'delete' && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
              {actionLoading === 'delete' ? t.webhook.delete.deleting : t.webhook.delete.confirm}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Payload Examples */}
      <PayloadExamples />
    </div>
  );
}
