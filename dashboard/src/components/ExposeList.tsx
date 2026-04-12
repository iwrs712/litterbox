import { useState } from 'react';
import { ExternalLink, Globe, Server, Trash2, Loader2, Link as LinkIcon } from 'lucide-react';
import { useSandboxStore } from '@/store/sandboxStore';
import { Button } from '@/components/ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
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
import type { ServiceExpose, ExposeStatus } from '@/types/sandbox';

interface ExposeListProps {
  sandboxId: string;
  exposes: ServiceExpose[];
  loading: boolean;
}

function ExposeStatusBadge({ status }: { status: ExposeStatus }) {
  const variants: Record<ExposeStatus, { variant: 'default' | 'secondary' | 'destructive'; label: string }> = {
    ready: { variant: 'default', label: 'Ready' },
    pending: { variant: 'secondary', label: 'Pending' },
    failed: { variant: 'destructive', label: 'Failed' },
  };

  const config = variants[status] || { variant: 'secondary', label: status };

  return (
    <Badge variant={config.variant}>
      {config.label}
    </Badge>
  );
}

export function ExposeList({ sandboxId, exposes, loading }: ExposeListProps) {
  const { deleteExpose, exposesLoading } = useSandboxStore();
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);

  const handleDelete = async () => {
    if (!deleteConfirm) return;
    try {
      await deleteExpose(deleteConfirm, sandboxId);
      setDeleteConfirm(null);
    } catch {
      // Error handled by store
    }
  };

  const formatExternalAccess = (expose: ServiceExpose) => {
    if (expose.protocol === 'http') {
      return expose.external_url || `http://${expose.domain}${expose.path || '/'}`;
    } else {
      return `${expose.external_ip}:${expose.external_port}`;
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        <span className="ml-2 text-muted-foreground">Loading service exposes...</span>
      </div>
    );
  }

  if (!exposes || exposes.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-8 text-center">
        <LinkIcon className="h-12 w-12 text-muted-foreground opacity-50 mb-4" />
        <p className="text-muted-foreground">No service exposes configured</p>
        <p className="text-xs text-muted-foreground mt-1">
          Create a service expose to make your sandbox services accessible externally
        </p>
      </div>
    );
  }

  return (
    <>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Protocol</TableHead>
            <TableHead>Internal Port</TableHead>
            <TableHead>External Access</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Created</TableHead>
            <TableHead className="text-right">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {exposes.map((expose) => (
            <TableRow key={expose.id}>
              <TableCell>
                <div className="flex items-center gap-2">
                  {expose.protocol === 'http' ? (
                    <Globe className="h-4 w-4 text-blue-500" />
                  ) : (
                    <Server className="h-4 w-4 text-purple-500" />
                  )}
                  <span className="font-medium uppercase">{expose.protocol}</span>
                </div>
              </TableCell>
              <TableCell>
                <code className="text-sm bg-muted px-2 py-1 rounded">
                  {expose.internal_port}
                </code>
              </TableCell>
              <TableCell>
                {expose.protocol === 'http' ? (
                  <div className="flex items-center gap-2">
                    <a
                      href={expose.external_url || `http://${expose.domain}${expose.path || '/'}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-primary hover:underline flex items-center gap-1 max-w-xs truncate"
                    >
                      {formatExternalAccess(expose)}
                      <ExternalLink className="h-3 w-3 flex-shrink-0" />
                    </a>
                  </div>
                ) : (
                  <div className="flex flex-col">
                    <code className="text-sm bg-muted px-2 py-1 rounded inline-block">
                      {formatExternalAccess(expose)}
                    </code>
                    {expose.external_ip && (
                      <span className="text-xs text-muted-foreground mt-1">
                        NodePort: {expose.external_port}
                      </span>
                    )}
                  </div>
                )}
              </TableCell>
              <TableCell>
                <ExposeStatusBadge status={expose.status} />
              </TableCell>
              <TableCell>
                <div className="text-sm">
                  {new Date(expose.created_at).toLocaleString()}
                </div>
              </TableCell>
              <TableCell className="text-right">
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={() => setDeleteConfirm(expose.id)}
                  disabled={exposesLoading}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      {/* Delete Confirmation Dialog */}
      <AlertDialog open={!!deleteConfirm} onOpenChange={() => setDeleteConfirm(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Service Expose</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete this service expose? This will remove external access to the service.
              This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDelete}
              className="bg-destructive text-destructive-foreground"
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
