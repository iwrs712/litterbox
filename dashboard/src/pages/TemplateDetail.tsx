import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useSandboxStore } from '@/store/sandboxStore';
import { useApp } from '@/contexts/AppContext';
import type { Template, PoolStatus } from '@/types/sandbox';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { ErrorAlert } from '@/components/ErrorAlert';
import { ArrowLeft, RefreshCw, FileCode, HardDrive, Cpu, Settings, Activity, Loader2 } from 'lucide-react';
import { formatDistanceToNow } from 'date-fns';

export function TemplateDetail() {
  const { templateId } = useParams<{ templateId: string }>();
  const { t } = useApp();
  const { templates, fetchTemplates, getPoolStatus, updatePool, loading, error, clearError } = useSandboxStore();

  const [template, setTemplate] = useState<Template | null>(null);
  const [poolStatus, setPoolStatus] = useState<PoolStatus | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [showPoolDialog, setShowPoolDialog] = useState(false);
  const [minReadyValue, setMinReadyValue] = useState<number>(5);
  const [targetReadyValue, setTargetReadyValue] = useState<number>(10);
  const [maxCreatingValue, setMaxCreatingValue] = useState<number>(5);

  const formatCpu = (cpuMillicores: number) => `${(cpuMillicores / 1000).toFixed(1)}c`;

  // Find template from store
  useEffect(() => {
    const found = templates.find(t => t.id === templateId);
    setTemplate(found || null);
  }, [templates, templateId]);

  // Fetch template if not in store - 模板是全局资源
  useEffect(() => {
    if (!template) {
      fetchTemplates();
    }
  }, [template, fetchTemplates]);

  // Fetch pool status
  const loadPoolStatus = async () => {
    if (!templateId) return;
    try {
      const status = await getPoolStatus(templateId);
      setPoolStatus(status);
    } catch (err) {
      console.error('Failed to fetch pool status:', err);
    }
  };

  useEffect(() => {
    loadPoolStatus();
    const interval = setInterval(loadPoolStatus, 5000); // Auto-refresh every 5s
    return () => clearInterval(interval);
  }, [templateId]);

  const handleRefresh = async () => {
    setActionLoading('refresh');
    // 模板是全局资源，不需要 tenant_id
    await fetchTemplates();
    await loadPoolStatus();
    setActionLoading(null);
  };

  const openPoolDialog = () => {
    setMinReadyValue(poolStatus?.min_ready ?? 5);
    setTargetReadyValue(poolStatus?.target_ready ?? 10);
    setMaxCreatingValue(poolStatus?.max_creating ?? 5);
    setShowPoolDialog(true);
  };

  const handleUpdatePool = async () => {
    if (!templateId) return;
    setActionLoading('pool');
    try {
      await updatePool(templateId, {
        min_ready: minReadyValue,
        target_ready: targetReadyValue,
        max_creating: maxCreatingValue,
      });
      await loadPoolStatus();
      await fetchTemplates();
      setShowPoolDialog(false);
    } catch (err) {
      // Error handled by store
    } finally {
      setActionLoading(null);
    }
  };

  if (loading && !template) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center">
          <Loader2 className="h-12 w-12 text-muted-foreground mx-auto mb-4 animate-spin" />
          <p className="text-muted-foreground">{t.template.detail.loading}</p>
        </div>
      </div>
    );
  }

  if (!template) {
    return (
      <div className="space-y-6">
        <Link to="/templates">
          <Button variant="ghost">
            <ArrowLeft className="mr-2 h-4 w-4" />
            {t.common.back}
          </Button>
        </Link>
        {error && <ErrorAlert error={error} onDismiss={clearError} />}
        <div className="text-center py-12">
          <p className="text-muted-foreground mb-4">{t.template.detail.notFound}</p>
          <Link to="/templates">
            <Button>{t.template.detail.backToList}</Button>
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link to="/templates">
            <Button variant="ghost" size="icon">
              <ArrowLeft className="h-4 w-4" />
            </Button>
          </Link>
          <div>
            <h1 className="text-3xl font-bold tracking-tight">{template.name}</h1>
            <p className="text-sm text-muted-foreground font-mono mt-1">{template.id}</p>
          </div>
        </div>
        <Button
          variant="outline"
          size="icon"
          onClick={handleRefresh}
          disabled={actionLoading === 'refresh'}
          title={t.common.refresh}
        >
          <RefreshCw className={`h-4 w-4 ${actionLoading === 'refresh' ? 'animate-spin' : ''}`} />
        </Button>
      </div>

      {error && <ErrorAlert error={error} onDismiss={clearError} />}

      {/* Template Configuration */}
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Cpu className="h-5 w-5" />
              {t.template.detail.computeResources}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <p className="text-sm text-muted-foreground">{t.template.detail.cpuCount}</p>
              <p className="text-2xl font-bold">{formatCpu(template.cpu_millicores)}</p>
            </div>
            <div>
              <p className="text-sm text-muted-foreground">{t.template.detail.memory}</p>
              <p className="text-2xl font-bold">{template.memory_mb} MB</p>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <FileCode className="h-5 w-5" />
              {t.template.detail.imageInfo}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <p className="text-sm text-muted-foreground">{t.template.detail.image}</p>
              <code className="text-sm bg-muted px-2 py-1 rounded break-all">
                {template.image}
              </code>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Command, Environment Variables, TTL, and Host Path Mounts */}
      {(template.command || (template.env && template.env.length > 0) || template.ttl_seconds || (template.host_path_mounts && template.host_path_mounts.length > 0)) && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Settings className="h-5 w-5" />
              Configuration
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {template.command && (
              <div>
                <p className="text-sm text-muted-foreground mb-2">Container Command</p>
                <code className="text-sm bg-muted px-3 py-2 rounded block">
                  {template.command}
                </code>
              </div>
            )}
            {template.env && template.env.length > 0 && (
              <div>
                <p className="text-sm text-muted-foreground mb-2">
                  Environment Variables ({template.env.length})
                </p>
                <div className="bg-muted px-3 py-2 rounded space-y-1 max-h-64 overflow-y-auto">
                  {template.env.map((envVar, index) => (
                    <code key={index} className="text-xs block">
                      {envVar}
                    </code>
                  ))}
                </div>
              </div>
            )}
            {template.ttl_seconds && (
              <div>
                <p className="text-sm text-muted-foreground mb-2">TTL (Time To Live)</p>
                <div className="bg-primary/10 text-primary px-3 py-2 rounded">
                  <span className="text-sm font-mono">
                    {template.ttl_seconds} seconds
                  </span>
                  <span className="text-xs text-muted-foreground ml-2">
                    ({Math.floor(template.ttl_seconds / 3600)}h {Math.floor((template.ttl_seconds % 3600) / 60)}m)
                  </span>
                </div>
              </div>
            )}
            {template.host_path_mounts && template.host_path_mounts.length > 0 && (
              <div>
                <p className="text-sm text-muted-foreground mb-2">
                  Host Path Mounts ({template.host_path_mounts.length})
                </p>
                <div className="space-y-2">
                  {template.host_path_mounts.map((mount, index) => (
                    <div key={index} className="bg-muted px-3 py-2 rounded border">
                      <div className="grid grid-cols-1 gap-1 text-xs">
                        <div>
                          <span className="text-muted-foreground">Host:</span>{' '}
                          <code className="font-mono">{mount.host_path}</code>
                        </div>
                        <div>
                          <span className="text-muted-foreground">Container:</span>{' '}
                          <code className="font-mono">{mount.container_path}</code>
                        </div>
                        <div>
                          <span className="text-muted-foreground">Mode:</span>{' '}
                          <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                            mount.read_only
                              ? 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200'
                              : 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200'
                          }`}>
                            {mount.read_only ? 'Read-Only' : 'Read-Write'}
                          </span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Pool Status */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              <HardDrive className="h-5 w-5" />
              {t.template.detail.poolStatus}
              {poolStatus?.ready ? (
                <span className="text-xs font-normal text-green-500 ml-2">
                  <Activity className="inline h-3 w-3 animate-pulse mr-1" />
                  {t.template.detail.poolReady}
                </span>
              ) : (
                <span className="text-xs font-normal text-yellow-500 ml-2">
                  {t.template.detail.poolNotReady}
                </span>
              )}
            </CardTitle>
            <Button variant="outline" size="sm" onClick={openPoolDialog}>
              <Settings className="mr-2 h-4 w-4" />
              {t.template.detail.configurePool}
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {poolStatus ? (
            <div className="space-y-6">
              <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-4">
                <div>
                  <p className="text-sm text-muted-foreground">{t.template.detail.minReady}</p>
                  <p className="text-2xl font-bold">{poolStatus.min_ready}</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">{t.template.detail.targetReady}</p>
                  <p className="text-2xl font-bold">{poolStatus.target_ready}</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">{t.template.detail.readyCount}</p>
                  <p className="text-2xl font-bold text-green-500">{poolStatus.ready}</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">{t.template.detail.allocated}</p>
                  <p className="text-2xl font-bold text-blue-500">{poolStatus.allocated}</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">{t.template.detail.creating}</p>
                  <p className="text-2xl font-bold text-yellow-500">{poolStatus.creating}</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">{t.template.detail.failed}</p>
                  <p className="text-2xl font-bold text-red-500">{poolStatus.failed}</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">{t.template.detail.terminating}</p>
                  <p className="text-2xl font-bold text-gray-500">{poolStatus.terminating}</p>
                </div>
              </div>

              {poolStatus.target_ready > 0 && (
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-sm font-medium">{t.template.detail.poolProgress}</span>
                    <span className="text-sm text-muted-foreground">
                      {poolStatus.ready} / {poolStatus.target_ready} ready
                      ({poolStatus.target_ready > 0 ? ((poolStatus.ready / poolStatus.target_ready) * 100).toFixed(0) : 0}%)
                    </span>
                  </div>
                  <div className="w-full bg-secondary rounded-full h-2.5">
                    <div
                      className="bg-green-500 h-2.5 rounded-full transition-all"
                      style={{
                        width: `${poolStatus.target_ready > 0 ? Math.min((poolStatus.ready / poolStatus.target_ready) * 100, 100) : 0}%`
                      }}
                    />
                  </div>
                </div>
              )}

              {!poolStatus.enabled && (
                <div className="py-6 text-center">
                  <p className="text-sm text-muted-foreground mb-2">
                    {t.template.detail.poolDisabled}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {t.template.detail.poolDisabledDescription}
                  </p>
                </div>
              )}
            </div>
          ) : (
            <div className="py-8 text-center">
              <Loader2 className="h-8 w-8 text-muted-foreground mx-auto mb-2 animate-spin" />
              <p className="text-sm text-muted-foreground">{t.template.detail.loadingPool}</p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Metadata */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FileCode className="h-5 w-5" />
            {t.template.detail.metadata}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div>
            <p className="text-sm text-muted-foreground">{t.template.detail.templateId}</p>
            <p className="font-mono">{template.id}</p>
          </div>
          {template.metadata?.user_id && (
            <div>
              <p className="text-sm text-muted-foreground">User ID</p>
              <p className="font-mono">{template.metadata.user_id}</p>
            </div>
          )}
          <div>
            <p className="text-sm text-muted-foreground">{t.template.detail.created}</p>
            <div className="flex flex-col">
              <p className="font-medium">{new Date(template.created_at).toLocaleString()}</p>
              <p className="text-xs text-muted-foreground">
                {formatDistanceToNow(new Date(template.created_at), { addSuffix: true })}
              </p>
            </div>
          </div>
          <div>
            <p className="text-sm text-muted-foreground">{t.template.detail.updated}</p>
            <div className="flex flex-col">
              <p className="font-medium">{new Date(template.updated_at).toLocaleString()}</p>
              <p className="text-xs text-muted-foreground">
                {formatDistanceToNow(new Date(template.updated_at), { addSuffix: true })}
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Pool Configuration Dialog */}
      <Dialog open={showPoolDialog} onOpenChange={setShowPoolDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t.template.pool.title}</DialogTitle>
            <DialogDescription>
              {t.template.pool.description}
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="pool-min-ready">{t.template.pool.minReadyLabel}</Label>
              <Input
                id="pool-min-ready"
                type="number"
                min="0"
                max="50"
                value={minReadyValue}
                onChange={(e) => setMinReadyValue(parseInt(e.target.value) || 0)}
                disabled={actionLoading === 'pool'}
              />
              <p className="text-xs text-muted-foreground">
                {t.template.pool.minReadyDescription}
              </p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="pool-target-ready">{t.template.pool.targetReadyLabel}</Label>
              <Input
                id="pool-target-ready"
                type="number"
                min="1"
                max="100"
                value={targetReadyValue}
                onChange={(e) => setTargetReadyValue(parseInt(e.target.value) || 1)}
                disabled={actionLoading === 'pool'}
              />
              <p className="text-xs text-muted-foreground">
                {t.template.pool.targetReadyDescription}
              </p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="pool-max-creating">{t.template.pool.maxCreatingLabel}</Label>
              <Input
                id="pool-max-creating"
                type="number"
                min="1"
                max="20"
                value={maxCreatingValue}
                onChange={(e) => setMaxCreatingValue(parseInt(e.target.value) || 5)}
                disabled={actionLoading === 'pool'}
              />
              <p className="text-xs text-muted-foreground">
                {t.template.pool.maxCreatingDescription}
              </p>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowPoolDialog(false)} disabled={actionLoading === 'pool'}>
              {t.common.cancel}
            </Button>
            <Button onClick={handleUpdatePool} disabled={actionLoading === 'pool'}>
              {actionLoading === 'pool' ? t.template.pool.updating : t.common.update}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
