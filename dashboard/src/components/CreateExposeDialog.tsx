import { useState } from 'react';
import { Globe, Server } from 'lucide-react';
import { useSandboxStore } from '@/store/sandboxStore';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import type { ExposeProtocol } from '@/types/sandbox';

interface CreateExposeDialogProps {
  sandboxId: string;
  sandboxName: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function CreateExposeDialog({
  sandboxId,
  sandboxName,
  open,
  onOpenChange,
}: CreateExposeDialogProps) {
  const { createExpose, exposesLoading } = useSandboxStore();

  const [protocol, setProtocol] = useState<ExposeProtocol>('http');
  const [internalPort, setInternalPort] = useState('');
  const [path, setPath] = useState('/');
  const [error, setError] = useState<string | null>(null);

  const validatePort = (port: string): boolean => {
    const portNum = parseInt(port, 10);
    return !isNaN(portNum) && portNum >= 1 && portNum <= 65535;
  };

  const handleCreate = async () => {
    // Validate internal port
    if (!internalPort.trim()) {
      setError('Internal port is required');
      return;
    }

    if (!validatePort(internalPort)) {
      setError('Port must be a number between 1 and 65535');
      return;
    }

    setError(null);

    try {
      await createExpose(sandboxId, {
        protocol,
        internal_port: parseInt(internalPort, 10),
        path: protocol === 'http' ? (path.trim() || '/') : undefined,
      });

      // Reset form and close dialog
      resetForm();
      onOpenChange(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create service expose');
    }
  };

  const resetForm = () => {
    setProtocol('http');
    setInternalPort('');
    setPath('/');
    setError(null);
  };

  const handleClose = () => {
    resetForm();
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Globe className="h-5 w-5" />
            Create Service Expose
          </DialogTitle>
          <DialogDescription>
            Expose a service running in sandbox: <span className="font-medium">{sandboxName}</span>
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* Protocol Selection */}
          <div className="space-y-2">
            <Label htmlFor="protocol">Protocol</Label>
            <Select
              value={protocol}
              onValueChange={(value: ExposeProtocol) => setProtocol(value)}
              disabled={exposesLoading}
            >
              <SelectTrigger id="protocol">
                <SelectValue placeholder="Select protocol" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="http">
                  <div className="flex items-center gap-2">
                    <Globe className="h-4 w-4" />
                    <div className="flex flex-col">
                      <span className="font-medium">HTTP</span>
                      <span className="text-xs text-muted-foreground">
                        Expose via Traefik Ingress with auto-generated domain
                      </span>
                    </div>
                  </div>
                </SelectItem>
                <SelectItem value="tcp">
                  <div className="flex items-center gap-2">
                    <Server className="h-4 w-4" />
                    <div className="flex flex-col">
                      <span className="font-medium">TCP</span>
                      <span className="text-xs text-muted-foreground">
                        Expose via NodePort with auto-assigned port
                      </span>
                    </div>
                  </div>
                </SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Internal Port */}
          <div className="space-y-2">
            <Label htmlFor="internal-port">Internal Port</Label>
            <Input
              id="internal-port"
              type="number"
              min="1"
              max="65535"
              value={internalPort}
              onChange={(e) => setInternalPort(e.target.value)}
              placeholder="e.g. 8080, 3306"
              disabled={exposesLoading}
            />
            <p className="text-xs text-muted-foreground">
              The port your service is listening on inside the sandbox (1-65535)
            </p>
          </div>

          {/* Path (HTTP only) */}
          {protocol === 'http' && (
            <div className="space-y-2">
              <Label htmlFor="path">Path (Optional)</Label>
              <Input
                id="path"
                value={path}
                onChange={(e) => setPath(e.target.value)}
                placeholder="/"
                disabled={exposesLoading}
              />
              <p className="text-xs text-muted-foreground">
                HTTP path prefix for routing. Default is "/"
              </p>
            </div>
          )}

          {/* Protocol Info */}
          <div className="rounded-md bg-muted p-3 text-sm">
            {protocol === 'http' ? (
              <div className="space-y-1">
                <p className="font-medium">HTTP Exposure</p>
                <p className="text-muted-foreground text-xs">
                  Your service will be accessible via an auto-generated domain like:
                  <code className="ml-1 bg-background px-1 rounded">
                    http://{sandboxId}.litterbox.example.com{path || '/'}
                  </code>
                </p>
              </div>
            ) : (
              <div className="space-y-1">
                <p className="font-medium">TCP Exposure</p>
                <p className="text-muted-foreground text-xs">
                  Your service will be accessible via a NodePort. You'll receive an external IP and port
                  after creation.
                </p>
              </div>
            )}
          </div>

          {error && (
            <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
              {error}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={handleClose} disabled={exposesLoading}>
            Cancel
          </Button>
          <Button
            onClick={handleCreate}
            disabled={exposesLoading || !internalPort.trim() || !validatePort(internalPort)}
          >
            {exposesLoading ? 'Creating...' : 'Create Expose'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}