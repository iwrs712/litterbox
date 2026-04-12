import { useEffect, useState } from 'react';
import { useSandboxStore } from '@/store/sandboxStore';
import { useApp } from '@/contexts/AppContext';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
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
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { ErrorAlert } from '@/components/ErrorAlert';
import { Database, Loader2, RefreshCw, Settings, Trash2, CheckCircle2, AlertCircle, Plus, ChevronDown, ChevronRight } from 'lucide-react';
import type { CreatePoolRequest, UpdatePoolRequest, Template } from '@/types/sandbox';

export function Pools() {
  const { t } = useApp();
  const {
    pools,
    templates,
    fetchPools,
    fetchTemplates,
    createPool,
    updatePool,
    deletePool,
    loading,
    error,
    clearError
  } = useSandboxStore();

  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [showEditDialog, setShowEditDialog] = useState(false);
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const [selectedPool, setSelectedPool] = useState<any>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(false);

  // Form state for create/edit
  const [selectedTemplateId, setSelectedTemplateId] = useState('');
  const [minReady, setMinReady] = useState(5);
  const [targetReady, setTargetReady] = useState(10);
  const [maxCreating, setMaxCreating] = useState(5);

  const formatCpu = (cpuMillicores: number) => `${(cpuMillicores / 1000).toFixed(1)}c`;

  useEffect(() => {
    fetchPools();
    fetchTemplates();

    // Auto-refresh every 5 seconds
    const interval = setInterval(() => {
      fetchPools();
    }, 5000);
    return () => clearInterval(interval);
  }, [fetchPools, fetchTemplates]);

  const handleRefresh = async () => {
    setActionLoading('refresh');
    await fetchPools();
    setActionLoading(null);
  };

  const resetForm = () => {
    setSelectedTemplateId('');
    setMinReady(5);
    setTargetReady(10);
    setMaxCreating(5);
    setShowAdvanced(false);
  };

  const openCreateDialog = () => {
    resetForm();
    setShowCreateDialog(true);
  };

  const openEditDialog = (pool: any) => {
    setSelectedPool(pool);
    setSelectedTemplateId(pool.template_id);
    setMinReady(pool.min_ready);
    setTargetReady(pool.target_ready);
    setMaxCreating(pool.max_creating);
    setShowAdvanced(pool.max_creating !== 5);
    setShowEditDialog(true);
  };

  const openDeleteDialog = (pool: any) => {
    setSelectedPool(pool);
    setShowDeleteDialog(true);
  };

  const handleCreatePool = async () => {
    if (!selectedTemplateId || minReady < 1) return;

    setActionLoading('create');
    try {
      const data: CreatePoolRequest = {
        min_ready: minReady,
        target_ready: targetReady,
      };

      if (showAdvanced) {
        data.max_creating = maxCreating;
      }

      await createPool(selectedTemplateId, data);
      setShowCreateDialog(false);
      resetForm();
    } catch (err) {
      // Error handled by store
    } finally {
      setActionLoading(null);
    }
  };

  const handleUpdatePool = async () => {
    if (!selectedPool) return;

    setActionLoading('update');
    try {
      const data: UpdatePoolRequest = {
        min_ready: minReady,
        target_ready: targetReady,
      };

      if (showAdvanced) {
        data.max_creating = maxCreating;
      }

      await updatePool(selectedPool.template_id, data);
      setShowEditDialog(false);
      setSelectedPool(null);
      resetForm();
    } catch (err) {
      // Error handled by store
    } finally {
      setActionLoading(null);
    }
  };

  const handleDeletePool = async () => {
    if (!selectedPool) return;

    setActionLoading('delete');
    try {
      await deletePool(selectedPool.template_id);
      setShowDeleteDialog(false);
      setSelectedPool(null);
    } catch (err) {
      // Error handled by store
    } finally {
      setActionLoading(null);
    }
  };

  const getStatusBadge = (pool: any) => {
    if (!pool.enabled) {
      return (
        <div className="flex items-center text-gray-500">
          <AlertCircle className="h-4 w-4 mr-1" />
          <span className="text-sm font-medium">Disabled</span>
        </div>
      );
    }
    if (pool.ready >= pool.min_ready) {
      return (
        <div className="flex items-center text-green-500">
          <CheckCircle2 className="h-4 w-4 mr-1" />
          <span className="text-sm font-medium">Healthy</span>
        </div>
      );
    }
    if (pool.ready === 0) {
      return (
        <div className="flex items-center text-red-500">
          <AlertCircle className="h-4 w-4 mr-1" />
          <span className="text-sm font-medium">Exhausted</span>
        </div>
      );
    }
    return (
      <div className="flex items-center text-yellow-500">
        <AlertCircle className="h-4 w-4 mr-1" />
        <span className="text-sm font-medium">Warming</span>
      </div>
    );
  };

  const getHealthIndicator = (pool: any) => {
    if (pool.ready === 0 && pool.min_ready > 0) {
      return <span className="text-red-500 text-xs">Exhausted</span>;
    } else if (pool.ready < pool.min_ready) {
      return <span className="text-yellow-500 text-xs">Warming ({pool.ready}/{pool.min_ready})</span>;
    } else {
      return <span className="text-green-500 text-xs">Healthy</span>;
    }
  };

  // Get templates that don't have pools configured
  const availableTemplates = templates?.filter(
    (template: Template) => !pools?.some((pool) => pool.template_id === template.id)
  ) || [];

  const getTemplateName = (templateId: string) => {
    const template = templates?.find((t: Template) => t.id === templateId);
    return template?.name || templateId;
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">{t.dashboard.pools.title}</h1>
          <p className="text-muted-foreground mt-2">{t.dashboard.pools.description}</p>
        </div>
        <div className="flex gap-2">
          <Button
            onClick={handleRefresh}
            disabled={actionLoading === 'refresh'}
            variant="outline"
          >
            <RefreshCw className={`h-4 w-4 mr-2 ${actionLoading === 'refresh' ? 'animate-spin' : ''}`} />
            {t.common.refresh}
          </Button>
          <Button
            onClick={openCreateDialog}
            disabled={availableTemplates.length === 0}
          >
            <Plus className="h-4 w-4 mr-2" />
            {t.dashboard.pools.createButton}
          </Button>
        </div>
      </div>

      {error && <ErrorAlert error={error} onDismiss={clearError} />}

      {/* Pools Table */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Database className="h-5 w-5" />
            Pool Status
          </CardTitle>
        </CardHeader>
        <CardContent>
          {loading && (!pools || pools.length === 0) ? (
            <div className="flex items-center justify-center p-12">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
          ) : !pools || pools.length === 0 ? (
            <div className="flex flex-col items-center justify-center p-12 text-center">
              <Database className="h-12 w-12 text-muted-foreground mb-4 opacity-50" />
              <p className="text-muted-foreground mb-2">{t.dashboard.pools.noPools}</p>
              <p className="text-xs text-muted-foreground">{t.dashboard.pools.noPoolsDescription}</p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t.dashboard.pools.columns.template}</TableHead>
                  <TableHead className="text-center">{t.dashboard.pools.columns.minReady}</TableHead>
                  <TableHead className="text-center">{t.dashboard.pools.columns.targetReady}</TableHead>
                  <TableHead className="text-center">{t.dashboard.pools.columns.ready}</TableHead>
                  <TableHead className="text-center">{t.dashboard.pools.columns.allocated}</TableHead>
                  <TableHead className="text-center">{t.dashboard.pools.columns.creating}</TableHead>
                  <TableHead className="text-center">{t.dashboard.pools.columns.failed}</TableHead>
                  <TableHead>{t.dashboard.pools.columns.status}</TableHead>
                  <TableHead className="text-right">{t.dashboard.pools.columns.actions}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {pools.map((pool) => (
                  <TableRow key={pool.template_id}>
                    <TableCell>
                      <div>
                        <div className="font-medium">{getTemplateName(pool.template_id)}</div>
                        <div className="text-xs text-muted-foreground font-mono">{pool.template_id}</div>
                      </div>
                    </TableCell>
                    <TableCell className="text-center">
                      <span className="text-lg font-bold">{pool.min_ready}</span>
                    </TableCell>
                    <TableCell className="text-center">
                      <span className="text-lg font-bold">{pool.target_ready}</span>
                    </TableCell>
                    <TableCell className="text-center">
                      <span className="text-lg font-bold text-green-500">{pool.ready}</span>
                      <div className="text-xs text-muted-foreground">{getHealthIndicator(pool)}</div>
                    </TableCell>
                    <TableCell className="text-center">
                      <span className="text-lg font-bold text-blue-500">{pool.allocated}</span>
                    </TableCell>
                    <TableCell className="text-center">
                      <span className="text-lg font-bold text-yellow-500">{pool.creating}</span>
                    </TableCell>
                    <TableCell className="text-center">
                      <span className="text-lg font-bold text-red-500">{pool.failed}</span>
                    </TableCell>
                    <TableCell>{getStatusBadge(pool)}</TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-2">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => openEditDialog(pool)}
                        >
                          <Settings className="h-4 w-4 mr-1" />
                          Edit
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => openDeleteDialog(pool)}
                        >
                          <Trash2 className="h-4 w-4 mr-1" />
                          Delete
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

      {/* Create Pool Dialog */}
      <Dialog open={showCreateDialog} onOpenChange={setShowCreateDialog}>
        <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t.dashboard.pools.create.title}</DialogTitle>
            <DialogDescription>
              {t.dashboard.pools.create.description}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-4">
            {/* Template Selection */}
            <div className="space-y-2">
              <Label>{t.dashboard.pools.create.selectTemplate}</Label>
              <Select value={selectedTemplateId} onValueChange={setSelectedTemplateId}>
                <SelectTrigger>
                  <SelectValue placeholder={t.dashboard.pools.create.selectTemplatePlaceholder} />
                </SelectTrigger>
                <SelectContent>
                  {availableTemplates.map((template: Template) => (
                    <SelectItem key={template.id} value={template.id}>
                      <div className="flex flex-col">
                        <span className="font-medium">{template.name}</span>
                        <span className="text-xs text-muted-foreground">
                          {template.image} • {formatCpu(template.cpu_millicores)} / {template.memory_mb}MB
                        </span>
                      </div>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Min Ready */}
            <div className="space-y-2">
              <Label htmlFor="min-ready">{t.dashboard.pools.create.minReadyLabel}</Label>
              <Input
                id="min-ready"
                type="number"
                min="1"
                max="50"
                value={minReady}
                onChange={(e) => setMinReady(parseInt(e.target.value) || 1)}
                placeholder={t.dashboard.pools.create.minReadyPlaceholder}
              />
            </div>

            {/* Target Ready */}
            <div className="space-y-2">
              <Label htmlFor="target-ready">{t.dashboard.pools.create.targetReadyLabel}</Label>
              <Input
                id="target-ready"
                type="number"
                min="1"
                max="100"
                value={targetReady}
                onChange={(e) => setTargetReady(parseInt(e.target.value) || 1)}
                placeholder={t.dashboard.pools.create.targetReadyPlaceholder}
              />
            </div>

            {/* Advanced Settings Toggle */}
            <div className="flex items-center space-x-2 cursor-pointer" onClick={() => setShowAdvanced(!showAdvanced)}>
              {showAdvanced ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
              <Label className="cursor-pointer">{t.dashboard.pools.create.advancedSettings}</Label>
            </div>

            {showAdvanced && (
              <div className="space-y-4 pl-6 border-l-2">
                {/* Max Creating */}
                <div className="space-y-2">
                  <Label htmlFor="max-creating">{t.dashboard.pools.create.maxCreatingLabel}</Label>
                  <Input
                    id="max-creating"
                    type="number"
                    min="1"
                    max="20"
                    value={maxCreating}
                    onChange={(e) => setMaxCreating(parseInt(e.target.value) || 5)}
                    placeholder={t.dashboard.pools.create.maxCreatingPlaceholder}
                  />
                </div>
              </div>
            )}
          </div>

          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setShowCreateDialog(false)}
              disabled={actionLoading === 'create'}
            >
              {t.common.cancel}
            </Button>
            <Button
              onClick={handleCreatePool}
              disabled={actionLoading === 'create' || !selectedTemplateId || minReady < 1}
            >
              {actionLoading === 'create' ? t.dashboard.pools.create.creating : t.common.create}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Edit Pool Dialog */}
      <Dialog open={showEditDialog} onOpenChange={setShowEditDialog}>
        <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t.dashboard.pools.edit.title}</DialogTitle>
            <DialogDescription>
              {t.dashboard.pools.edit.description}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-4">
            {/* Template (Read-only) */}
            <div className="space-y-2">
              <Label>Template</Label>
              <Input
                value={getTemplateName(selectedTemplateId)}
                disabled
                className="bg-muted"
              />
              <p className="text-xs text-muted-foreground font-mono">{selectedTemplateId}</p>
            </div>

            {/* Min Ready */}
            <div className="space-y-2">
              <Label htmlFor="edit-min-ready">{t.dashboard.pools.create.minReadyLabel}</Label>
              <Input
                id="edit-min-ready"
                type="number"
                min="0"
                max="50"
                value={minReady}
                onChange={(e) => setMinReady(parseInt(e.target.value) || 0)}
                placeholder={t.dashboard.pools.create.minReadyPlaceholder}
              />
              <p className="text-xs text-muted-foreground">Set to 0 to disable pool</p>
            </div>

            {/* Target Ready */}
            <div className="space-y-2">
              <Label htmlFor="edit-target-ready">{t.dashboard.pools.create.targetReadyLabel}</Label>
              <Input
                id="edit-target-ready"
                type="number"
                min="1"
                max="100"
                value={targetReady}
                onChange={(e) => setTargetReady(parseInt(e.target.value) || 1)}
                placeholder={t.dashboard.pools.create.targetReadyPlaceholder}
              />
            </div>

            {/* Advanced Settings Toggle */}
            <div className="flex items-center space-x-2 cursor-pointer" onClick={() => setShowAdvanced(!showAdvanced)}>
              {showAdvanced ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
              <Label className="cursor-pointer">{t.dashboard.pools.create.advancedSettings}</Label>
            </div>

            {showAdvanced && (
              <div className="space-y-4 pl-6 border-l-2">
                {/* Max Creating */}
                <div className="space-y-2">
                  <Label htmlFor="edit-max-creating">{t.dashboard.pools.create.maxCreatingLabel}</Label>
                  <Input
                    id="edit-max-creating"
                    type="number"
                    min="1"
                    max="20"
                    value={maxCreating}
                    onChange={(e) => setMaxCreating(parseInt(e.target.value) || 5)}
                    placeholder={t.dashboard.pools.create.maxCreatingPlaceholder}
                  />
                </div>
              </div>
            )}
          </div>

          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setShowEditDialog(false)}
              disabled={actionLoading === 'update'}
            >
              {t.common.cancel}
            </Button>
            <Button
              onClick={handleUpdatePool}
              disabled={actionLoading === 'update'}
            >
              {actionLoading === 'update' ? t.dashboard.pools.edit.updating : t.common.save}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Pool Dialog */}
      <Dialog open={showDeleteDialog} onOpenChange={setShowDeleteDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t.dashboard.pools.delete.title}</DialogTitle>
            <DialogDescription>
              {t.dashboard.pools.delete.description}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label>Template</Label>
              <Input
                value={selectedPool ? getTemplateName(selectedPool.template_id) : ''}
                disabled
                className="bg-muted"
              />
            </div>

            <div className="rounded-md bg-yellow-500/10 p-3 text-sm text-yellow-700 dark:text-yellow-400">
              <p className="font-semibold">Warning:</p>
              <p>{t.dashboard.pools.delete.warning}</p>
            </div>
          </div>

          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setShowDeleteDialog(false)}
              disabled={actionLoading === 'delete'}
            >
              {t.common.cancel}
            </Button>
            <Button
              variant="destructive"
              onClick={handleDeletePool}
              disabled={actionLoading === 'delete'}
            >
              {actionLoading === 'delete' ? t.dashboard.pools.delete.deleting : t.common.delete}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
