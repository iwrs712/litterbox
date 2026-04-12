import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Loader2, Plus, Trash2, Terminal, Filter } from 'lucide-react';
import { useSandboxStore } from '@/store/sandboxStore';
import { useApp } from '@/contexts/AppContext';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
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
import { SandboxStatusBadge } from '@/components/SandboxStatusBadge';
import { PoolStateBadge } from '@/components/PoolStateBadge';
import { CreateSandboxDialog } from '@/components/CreateSandboxDialog';
import { SandboxFilters, type SandboxFiltersState } from '@/components/SandboxFilters';
import { ErrorAlert } from '@/components/ErrorAlert';

export function Sandboxes() {
  const { t } = useApp();
  const { sandboxes, templates, fetchSandboxes, fetchTemplates, deleteSandbox, loading, error, clearError } =
    useSandboxStore();

  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);
  // 默认过滤器：显示用户相关的沙箱（allocated 或 direct）
  const [filters, setFilters] = useState<SandboxFiltersState>({
    pool_state: 'user-sandboxes', // 特殊值表示 allocated 或 none
  });
  const [showFilters, setShowFilters] = useState(false);

  const formatCpu = (cpuMillicores: number) => `${(cpuMillicores / 1000).toFixed(1)}c`;

  useEffect(() => {
    // 加载沙盒列表
    // 处理特殊的 pool_state 值
    const queryFilters = { ...filters };
    if (filters.pool_state === 'user-sandboxes') {
      // 默认不传 pool_state，在客户端过滤
      delete queryFilters.pool_state;
    }
    fetchSandboxes(queryFilters);
    fetchTemplates();
  }, [fetchSandboxes, fetchTemplates]);

  const handleSearch = () => {
    const queryFilters = { ...filters };
    if (filters.pool_state === 'user-sandboxes') {
      // 默认不传 pool_state，在客户端过滤
      delete queryFilters.pool_state;
    }
    fetchSandboxes(queryFilters);
  };

  const handleResetFilters = () => {
    const defaultFilters = { pool_state: 'user-sandboxes' };
    setFilters(defaultFilters);
    fetchSandboxes({});
  };

  // 根据 pool_state 过滤沙箱
  const filteredSandboxes = sandboxes?.filter(sandbox => {
    if (filters.pool_state === 'user-sandboxes') {
      // 只显示 allocated 或 none（用户直接创建的）
      return sandbox.pool_state === 'allocated' || sandbox.pool_state === 'none';
    }
    return true; // 其他情况显示所有沙箱
  });

  const handleDelete = async () => {
    if (!deleteConfirm) return;
    try {
      await deleteSandbox(deleteConfirm);
      setDeleteConfirm(null);
    } catch (err) {
      // Error handled by store
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">{t.sandbox.list.title}</h1>
          <p className="text-muted-foreground mt-2">
            Manage your sandboxes
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            onClick={() => setShowFilters(!showFilters)}
          >
            <Filter className="h-4 w-4 mr-2" />
            {showFilters ? 'Hide Filters' : 'Show Filters'}
          </Button>
          <Button onClick={() => setShowCreateDialog(true)}>
            <Plus className="h-4 w-4 mr-2" />
            {t.sandbox.list.createButton}
          </Button>
        </div>
      </div>

      {error && <ErrorAlert error={error} onDismiss={clearError} />}

      {/* Filters */}
      {showFilters && (
        <SandboxFilters
          filters={filters}
          onFiltersChange={setFilters}
          onSearch={handleSearch}
          onReset={handleResetFilters}
          templates={templates}
        />
      )}

      {/* Sandboxes Table */}
      <Card>
        {loading && (!filteredSandboxes || filteredSandboxes.length === 0) ? (
          <div className="flex items-center justify-center p-12">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          </div>
        ) : !filteredSandboxes || filteredSandboxes.length === 0 ? (
          <div className="flex flex-col items-center justify-center p-12 text-center">
            <p className="text-muted-foreground">{t.sandbox.list.noSandboxes}</p>
            <Button
              variant="outline"
              className="mt-4"
              onClick={() => setShowCreateDialog(true)}
            >
              <Plus className="h-4 w-4 mr-2" />
              {t.sandbox.list.createButton}
            </Button>
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t.sandbox.list.columns.name}</TableHead>
                <TableHead>{t.sandbox.list.columns.template}</TableHead>
                <TableHead>{t.sandbox.list.columns.status}</TableHead>
                <TableHead>{t.sandbox.list.columns.resources}</TableHead>
                <TableHead>{t.sandbox.list.columns.poolInfo}</TableHead>
                <TableHead>Metadata</TableHead>
                <TableHead>{t.sandbox.list.columns.createdAt}</TableHead>
                <TableHead>Expires</TableHead>
                <TableHead className="text-right">{t.common.actions}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredSandboxes?.map((sandbox) => (
                <TableRow key={sandbox.id}>
                  <TableCell className="font-medium">
                    <Link
                      to={`/sandboxes/${sandbox.id}`}
                      className="hover:underline text-primary"
                    >
                      {sandbox.name}
                    </Link>
                    <div className="text-xs text-muted-foreground mt-1">
                      {sandbox.id}
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="text-sm">{sandbox.template_id}</div>
                    <div className="text-xs text-muted-foreground">
                      {sandbox.image}
                    </div>
                  </TableCell>
                  <TableCell>
                    <SandboxStatusBadge status={sandbox.status} />
                  </TableCell>
                  <TableCell>
                    <div className="text-sm space-y-1">
                      <div>{formatCpu(sandbox.cpu_millicores)}</div>
                      <div>{sandbox.memory_mb}MB</div>
                    </div>
                  </TableCell>
                  <TableCell>
                    <PoolStateBadge poolState={sandbox.pool_state} />
                  </TableCell>
                  <TableCell>
                    {sandbox.metadata && Object.keys(sandbox.metadata).length > 0 ? (
                      <div className="text-xs space-y-1 max-w-xs">
                        {Object.entries(sandbox.metadata).slice(0, 2).map(([key, value]) => (
                          <div key={key} className="truncate">
                            <span className="font-mono text-muted-foreground">{key}:</span>{' '}
                            <span className="font-mono">{String(value)}</span>
                          </div>
                        ))}
                        {Object.keys(sandbox.metadata).length > 2 && (
                          <div className="text-muted-foreground">
                            +{Object.keys(sandbox.metadata).length - 2} more...
                          </div>
                        )}
                      </div>
                    ) : (
                      <span className="text-xs text-muted-foreground">-</span>
                    )}
                  </TableCell>
                  <TableCell>
                    <div className="text-sm">
                      {new Date(sandbox.created_at).toLocaleString()}
                    </div>
                  </TableCell>
                  <TableCell>
                    {sandbox.expires_at ? (
                      <div className="text-sm space-y-1">
                        <div>{new Date(sandbox.expires_at).toLocaleString()}</div>
                        {sandbox.time_remaining_seconds !== undefined && (
                          <div className={`text-xs font-medium ${
                            sandbox.time_remaining_seconds <= 60
                              ? 'text-destructive'
                              : sandbox.time_remaining_seconds <= 300
                              ? 'text-yellow-500'
                              : 'text-muted-foreground'
                          }`}>
                            {sandbox.time_remaining_seconds > 0
                              ? `${Math.floor(sandbox.time_remaining_seconds / 60)}m ${sandbox.time_remaining_seconds % 60}s left`
                              : 'Expired'}
                          </div>
                        )}
                      </div>
                    ) : (
                      <span className="text-xs text-muted-foreground">-</span>
                    )}
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex items-center justify-end gap-2">
                      {sandbox.status === 'running' && (
                        <Button
                          variant="outline"
                          size="sm"
                          asChild
                          title={t.sandbox.terminal.title}
                        >
                          <a
                            href={`/sandboxes/${sandbox.id}/terminal`}
                            target="_blank"
                            rel="noopener noreferrer"
                          >
                            <Terminal className="h-4 w-4" />
                          </a>
                        </Button>
                      )}
                      <Button
                        variant="destructive"
                        size="sm"
                        onClick={() => setDeleteConfirm(sandbox.id)}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Card>

      {/* Dialogs */}
      <CreateSandboxDialog open={showCreateDialog} onOpenChange={setShowCreateDialog} />

      <AlertDialog open={!!deleteConfirm} onOpenChange={() => setDeleteConfirm(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t.sandbox.delete.title}</AlertDialogTitle>
            <AlertDialogDescription>
              {t.sandbox.delete.description}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t.common.cancel}</AlertDialogCancel>
            <AlertDialogAction onClick={handleDelete}>
              {t.sandbox.delete.confirm}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
