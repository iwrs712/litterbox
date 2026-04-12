import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useSandboxStore } from '@/store/sandboxStore';
import { useApp } from '@/contexts/AppContext';
import type { Sandbox } from '@/types/sandbox';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
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
import { SandboxStatusBadge } from '@/components/SandboxStatusBadge';
import { PoolStateBadge } from '@/components/PoolStateBadge';
import { ExposeList } from '@/components/ExposeList';
import { CreateExposeDialog } from '@/components/CreateExposeDialog';
import { ArrowLeft, RefreshCw, Cpu, HardDrive, FileCode, Trash2, Loader2, Server, Globe, Plus, Terminal } from 'lucide-react';
import { formatDistanceToNow } from 'date-fns';

export function SandboxDetail() {
  const { sandboxId } = useParams<{ sandboxId: string }>();
  const { t } = useApp();
  const { 
    sandboxes, 
    fetchSandboxes, 
    deleteSandbox, 
    loading, 
    error, 
    clearError,
    exposes,
    exposesLoading,
    fetchExposes,
    clearExposes,
  } = useSandboxStore();

  const [sandbox, setSandbox] = useState<Sandbox | null>(null);
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const [showCreateExposeDialog, setShowCreateExposeDialog] = useState(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const formatCpu = (cpuMillicores: number) => `${(cpuMillicores / 1000).toFixed(1)}c`;

  // Find sandbox from store
  useEffect(() => {
    const found = sandboxes.find(s => s.id === sandboxId);
    setSandbox(found || null);
  }, [sandboxes, sandboxId]);

  // Fetch sandbox if not in store - 管理员模式获取所有沙盒
  useEffect(() => {
    if (!sandbox) {
      fetchSandboxes();
    }
  }, [sandbox, fetchSandboxes]);

  // Fetch service exposes when sandbox is loaded
  useEffect(() => {
    if (sandboxId && sandbox) {
      fetchExposes(sandboxId);
    }
    return () => {
      clearExposes();
    };
  }, [sandboxId, sandbox, fetchExposes, clearExposes]);

  const handleRefresh = async () => {
    setActionLoading('refresh');
    await fetchSandboxes();
    if (sandboxId) {
      await fetchExposes(sandboxId);
    }
    setActionLoading(null);
  };

  const handleDelete = async () => {
    if (!sandboxId) return;
    setActionLoading('delete');
    try {
      await deleteSandbox(sandboxId);
      // Navigate back to sandboxes list after successful deletion
      window.location.href = '/sandboxes';
    } catch (err) {
      // Error handled by store
      setActionLoading(null);
    }
  };

  if (loading && !sandbox) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center">
          <Loader2 className="h-12 w-12 text-muted-foreground mx-auto mb-4 animate-spin" />
          <p className="text-muted-foreground">{t.sandbox.detail.loading}</p>
        </div>
      </div>
    );
  }

  if (!sandbox) {
    return (
      <div className="space-y-6">
        <Link to="/sandboxes">
          <Button variant="ghost">
            <ArrowLeft className="mr-2 h-4 w-4" />
            {t.common.back}
          </Button>
        </Link>
        {error && <ErrorAlert error={error} onDismiss={clearError} />}
        <div className="text-center py-12">
          <p className="text-muted-foreground mb-4">{t.sandbox.detail.notFound}</p>
          <Link to="/sandboxes">
            <Button>{t.sandbox.detail.backToList}</Button>
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link to="/sandboxes">
            <Button variant="ghost" size="icon">
              <ArrowLeft className="h-4 w-4" />
            </Button>
          </Link>
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-3xl font-bold tracking-tight">{sandbox.name}</h1>
              <SandboxStatusBadge status={sandbox.status} />
            </div>
            <p className="text-sm text-muted-foreground font-mono mt-1">{sandbox.id}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="icon"
            onClick={handleRefresh}
            disabled={actionLoading === 'refresh'}
            title={t.common.refresh}
          >
            <RefreshCw className={`h-4 w-4 ${actionLoading === 'refresh' ? 'animate-spin' : ''}`} />
          </Button>
          {sandbox.status === 'running' && (
            <Button variant="outline" asChild title="Open Terminal">
              <a
                href={`/sandboxes/${sandbox.id}/terminal`}
                target="_blank"
                rel="noopener noreferrer"
              >
                <Terminal className="mr-2 h-4 w-4" />
                Terminal
              </a>
            </Button>
          )}
          <Button
            variant="destructive"
            onClick={() => setShowDeleteDialog(true)}
            disabled={actionLoading === 'delete'}
          >
            <Trash2 className="mr-2 h-4 w-4" />
            {t.sandbox.detail.delete}
          </Button>
        </div>
      </div>

      {error && <ErrorAlert error={error} onDismiss={clearError} />}

      {/* Resource Configuration */}
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Cpu className="h-5 w-5" />
              {t.sandbox.detail.resources}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <p className="text-sm text-muted-foreground">{t.sandbox.detail.cpuCount}</p>
              <p className="text-2xl font-bold">{formatCpu(sandbox.cpu_millicores)}</p>
            </div>
            <div>
              <p className="text-sm text-muted-foreground">{t.sandbox.detail.memory}</p>
              <p className="text-2xl font-bold">{sandbox.memory_mb} MB</p>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Server className="h-5 w-5" />
              {t.sandbox.detail.templateInfo}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <p className="text-sm text-muted-foreground">{t.sandbox.detail.templateId}</p>
              <Link
                to={`/templates/${sandbox.template_id}`}
                className="text-primary hover:underline font-mono text-sm"
              >
                {sandbox.template_id}
              </Link>
            </div>
            <div>
              <p className="text-sm text-muted-foreground">{t.sandbox.detail.image}</p>
              <code className="text-sm bg-muted px-2 py-1 rounded break-all">
                {sandbox.image}
              </code>
            </div>
            <div>
              <p className="text-sm text-muted-foreground">{t.sandbox.detail.status}</p>
              <div className="mt-1">
                <SandboxStatusBadge status={sandbox.status} />
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Pool Information */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <HardDrive className="h-5 w-5" />
            {t.sandbox.detail.poolInfo}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <p className="text-sm text-muted-foreground">{t.sandbox.detail.poolState}</p>
              <div className="mt-1">
                <PoolStateBadge poolState={sandbox.pool_state} />
              </div>
            </div>
            {sandbox.allocated_at && (
              <div>
                <p className="text-sm text-muted-foreground">Allocated At</p>
                <p className="text-lg font-medium">
                  {formatDistanceToNow(new Date(sandbox.allocated_at), { addSuffix: true })}
                </p>
              </div>
            )}
          </div>
          {sandbox.pool_state !== 'none' && (
            <div className="rounded-lg bg-muted p-3 text-sm">
              <p className="text-muted-foreground">
                {t.sandbox.detail.poolManagedDescription}
              </p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Service Exposes */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              <Globe className="h-5 w-5" />
              Service Exposes
            </CardTitle>
            {sandbox.status === 'running' && (
              <Button
                size="sm"
                onClick={() => setShowCreateExposeDialog(true)}
              >
                <Plus className="h-4 w-4 mr-2" />
                Create Expose
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent>
          <ExposeList
            sandboxId={sandbox.id}
            exposes={exposes}
            loading={exposesLoading}
          />
          {sandbox.status !== 'running' && (
            <div className="mt-4 rounded-lg bg-muted p-3 text-sm">
              <p className="text-muted-foreground">
                Service exposes can only be created when the sandbox is running.
              </p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Metadata */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FileCode className="h-5 w-5" />
            {t.sandbox.detail.metadata}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div>
            <p className="text-sm text-muted-foreground">{t.sandbox.detail.sandboxId}</p>
            <p className="font-mono text-sm">{sandbox.id}</p>
          </div>
          <div>
            <p className="text-sm text-muted-foreground">{t.sandbox.detail.created}</p>
            <div className="flex flex-col">
              <p className="font-medium">{new Date(sandbox.created_at).toLocaleString()}</p>
              <p className="text-xs text-muted-foreground">
                {formatDistanceToNow(new Date(sandbox.created_at), { addSuffix: true })}
              </p>
            </div>
          </div>
          <div>
            <p className="text-sm text-muted-foreground">{t.sandbox.detail.updated}</p>
            <div className="flex flex-col">
              <p className="font-medium">{new Date(sandbox.updated_at).toLocaleString()}</p>
              <p className="text-xs text-muted-foreground">
                {formatDistanceToNow(new Date(sandbox.updated_at), { addSuffix: true })}
              </p>
            </div>
          </div>
          {sandbox.metadata && Object.keys(sandbox.metadata).length > 0 && (
            <div>
              <p className="text-sm text-muted-foreground mb-2">{t.sandbox.detail.customMetadata}</p>
              <div className="rounded-md border p-3 space-y-2">
                {Object.entries(sandbox.metadata).map(([key, value]) => (
                  <div key={key} className="flex justify-between items-start">
                    <span className="text-sm font-medium">{key}:</span>
                    <span className="text-sm text-muted-foreground text-right break-all ml-2">
                      {typeof value === 'object' ? JSON.stringify(value) : String(value)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Create Expose Dialog */}
      <CreateExposeDialog
        sandboxId={sandbox.id}
        sandboxName={sandbox.name}
        open={showCreateExposeDialog}
        onOpenChange={setShowCreateExposeDialog}
      />

      {/* Delete Confirmation Dialog */}
      <AlertDialog open={showDeleteDialog} onOpenChange={setShowDeleteDialog}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t.sandbox.delete.title}</AlertDialogTitle>
            <AlertDialogDescription>
              {t.sandbox.delete.description}
              <br />
              <br />
              <span className="font-mono text-sm">
                {sandbox.id} - {sandbox.name}
              </span>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t.common.cancel}</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDelete}
              className="bg-destructive text-destructive-foreground"
              disabled={actionLoading === 'delete'}
            >
              {actionLoading === 'delete' ? t.sandbox.delete.deleting : t.sandbox.delete.confirm}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
