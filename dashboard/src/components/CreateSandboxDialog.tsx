import { useState, useEffect } from 'react';
import { HardDrive, Plus, X } from 'lucide-react';
import { useSandboxStore } from '@/store/sandboxStore';
import { useApp } from '@/contexts/AppContext';
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
import { Textarea } from '@/components/ui/textarea';
import { Switch } from '@/components/ui/switch';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

interface CreateSandboxDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

interface MetadataEntry {
  id: string;
  key: string;
  value: string;
}

const formatCpu = (cpuMillicores: number) => `${(cpuMillicores / 1000).toFixed(1)}c`;
const DEFAULT_WORKSPACE = {
  enabled: true,
  mountPath: '/workspace',
  size: '1Gi',
  storageClass: 'litterbox-workspace-lvm',
};

export function CreateSandboxDialog({ open, onOpenChange }: CreateSandboxDialogProps) {
  const { t } = useApp();
  const { templates, fetchTemplates, createSandbox, loading } = useSandboxStore();

  const [name, setName] = useState('');
  const [templateId, setTemplateId] = useState('');
  const [envText, setEnvText] = useState('');
  const [metadataEntries, setMetadataEntries] = useState<MetadataEntry[]>([]);
  const [customWorkspace, setCustomWorkspace] = useState(false);
  const [workspaceEnabled, setWorkspaceEnabled] = useState(DEFAULT_WORKSPACE.enabled);
  const [workspaceMountPath, setWorkspaceMountPath] = useState(DEFAULT_WORKSPACE.mountPath);
  const [workspaceSize, setWorkspaceSize] = useState(DEFAULT_WORKSPACE.size);
  const [workspaceStorageClass, setWorkspaceStorageClass] = useState(DEFAULT_WORKSPACE.storageClass);
  const [error, setError] = useState<string | null>(null);

  const resetWorkspace = () => {
    setCustomWorkspace(false);
    setWorkspaceEnabled(DEFAULT_WORKSPACE.enabled);
    setWorkspaceMountPath(DEFAULT_WORKSPACE.mountPath);
    setWorkspaceSize(DEFAULT_WORKSPACE.size);
    setWorkspaceStorageClass(DEFAULT_WORKSPACE.storageClass);
  };

  // 加载模板列表
  useEffect(() => {
    if (open) {
      fetchTemplates();
    }
  }, [open, fetchTemplates]);

  const addMetadataEntry = () => {
    setMetadataEntries([
      ...metadataEntries,
      { id: Math.random().toString(), key: '', value: '' },
    ]);
  };

  const removeMetadataEntry = (id: string) => {
    setMetadataEntries(metadataEntries.filter((entry) => entry.id !== id));
  };

  const updateMetadataEntry = (id: string, field: 'key' | 'value', value: string) => {
    setMetadataEntries(
      metadataEntries.map((entry) =>
        entry.id === id ? { ...entry, [field]: value } : entry
      )
    );
  };

  const handleCreate = async () => {
    if (!name.trim()) {
      setError('Sandbox name is required');
      return;
    }

    if (!templateId) {
      setError('Template is required');
      return;
    }

    setError(null);

    try {
      // 构建元数据对象
      const metadata: Record<string, string> = {};
      metadataEntries.forEach((entry) => {
        if (entry.key.trim()) {
          metadata[entry.key.trim()] = entry.value;
        }
      });
      const env = envText
        .split('\n')
        .map((line) => line.trim())
        .filter((line) => line.length > 0);

      await createSandbox({
        name: name.trim(),
        template_id: templateId,
        metadata: Object.keys(metadata).length > 0 ? metadata : undefined,
        env: env.length > 0 ? env : undefined,
        workspace: customWorkspace
          ? {
              enabled: workspaceEnabled,
              ...(workspaceMountPath.trim() ? { mount_path: workspaceMountPath.trim() } : {}),
              ...(workspaceSize.trim() ? { size: workspaceSize.trim() } : {}),
              ...(workspaceStorageClass.trim() ? { storage_class: workspaceStorageClass.trim() } : {}),
            }
          : undefined,
      });

      // 重置表单
      setName('');
      setTemplateId('');
      setEnvText('');
      setMetadataEntries([]);
      resetWorkspace();
      onOpenChange(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create sandbox');
    }
  };

  const handleClose = () => {
    setName('');
    setTemplateId('');
    setEnvText('');
    setMetadataEntries([]);
    resetWorkspace();
    setError(null);
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t.sandbox.create.title}</DialogTitle>
          <DialogDescription>
            Enter sandbox name and select a template to create a new sandbox.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* Sandbox Name */}
          <div className="space-y-2">
            <Label htmlFor="sandbox-name">{t.sandbox.create.nameLabel}</Label>
            <Input
              id="sandbox-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t.sandbox.create.namePlaceholder}
              disabled={loading}
            />
          </div>

          {/* Template Selection */}
          <div className="space-y-2">
            <Label htmlFor="template">{t.sandbox.create.templateLabel}</Label>
            <Select
              value={templateId}
              onValueChange={(value) => {
                setTemplateId(value);
                resetWorkspace();
              }}
              disabled={loading}
            >
              <SelectTrigger id="template">
                <SelectValue placeholder={t.sandbox.create.templatePlaceholder} />
              </SelectTrigger>
              <SelectContent>
                {!templates || templates.length === 0 ? (
                  <div className="p-2 text-sm text-muted-foreground">
                    {t.template.list.noTemplates}
                  </div>
                ) : (
                  templates?.map((template) => (
                    <SelectItem key={template.id} value={template.id}>
                      <div className="flex flex-col">
                        <span className="font-medium">{template.name}</span>
                        <span className="text-xs text-muted-foreground">
                          {template.image} • {formatCpu(template.cpu_millicores)} / {template.memory_mb}MB
                        </span>
                      </div>
                    </SelectItem>
                  ))
                )}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-3 border-t pt-4">
            <div className="flex items-center justify-between gap-4">
              <div className="flex items-center gap-2">
                <HardDrive className="h-4 w-4 text-muted-foreground" />
                <Label htmlFor="sandbox-custom-workspace">Custom workspace</Label>
              </div>
              <Switch
                id="sandbox-custom-workspace"
                checked={customWorkspace}
                onCheckedChange={setCustomWorkspace}
                disabled={loading}
              />
            </div>
            {customWorkspace && (
              <div className="space-y-3 border-l-2 pl-4">
                <div className="flex items-center justify-between gap-4">
                  <Label htmlFor="sandbox-workspace-enabled">Persistent workspace</Label>
                  <Switch
                    id="sandbox-workspace-enabled"
                    checked={workspaceEnabled}
                    onCheckedChange={setWorkspaceEnabled}
                    disabled={loading}
                  />
                </div>
                {workspaceEnabled && (
                  <div className="grid gap-3 sm:grid-cols-3">
                    <div className="space-y-2">
                      <Label htmlFor="sandbox-workspace-path">Mount path</Label>
                      <Input
                        id="sandbox-workspace-path"
                        value={workspaceMountPath}
                        onChange={(e) => setWorkspaceMountPath(e.target.value)}
                        placeholder={DEFAULT_WORKSPACE.mountPath}
                        disabled={loading}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="sandbox-workspace-size">PVC size</Label>
                      <Input
                        id="sandbox-workspace-size"
                        value={workspaceSize}
                        onChange={(e) => setWorkspaceSize(e.target.value)}
                        placeholder={DEFAULT_WORKSPACE.size}
                        disabled={loading}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="sandbox-workspace-storage">StorageClass</Label>
                      <Input
                        id="sandbox-workspace-storage"
                        value={workspaceStorageClass}
                        onChange={(e) => setWorkspaceStorageClass(e.target.value)}
                        placeholder={DEFAULT_WORKSPACE.storageClass}
                        disabled={loading}
                      />
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Environment Variables (Optional) */}
          <div className="space-y-2">
            <Label htmlFor="sandbox-env">{t.sandbox.create.envLabel}</Label>
            <Textarea
              id="sandbox-env"
              value={envText}
              onChange={(e) => setEnvText(e.target.value)}
              placeholder={t.sandbox.create.envPlaceholder}
              disabled={loading}
              className="font-mono"
              rows={4}
            />
            <p className="text-xs text-muted-foreground">
              {t.sandbox.create.envHelp}
            </p>
          </div>

          {/* Metadata (Optional) */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label>{t.sandbox.create.metadataLabel}</Label>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={addMetadataEntry}
                disabled={loading}
              >
                <Plus className="h-4 w-4 mr-1" />
                Add Field
              </Button>
            </div>

            {metadataEntries.length > 0 && (
              <div className="space-y-2 border rounded-md p-3">
                {metadataEntries.map((entry) => (
                  <div key={entry.id} className="flex gap-2">
                    <Input
                      placeholder="Key"
                      value={entry.key}
                      onChange={(e) =>
                        updateMetadataEntry(entry.id, 'key', e.target.value)
                      }
                      disabled={loading}
                      className="flex-1"
                    />
                    <Input
                      placeholder="Value"
                      value={entry.value}
                      onChange={(e) =>
                        updateMetadataEntry(entry.id, 'value', e.target.value)
                      }
                      disabled={loading}
                      className="flex-1"
                    />
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      onClick={() => removeMetadataEntry(entry.id)}
                      disabled={loading}
                    >
                      <X className="h-4 w-4" />
                    </Button>
                  </div>
                ))}
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
          <Button variant="outline" onClick={handleClose} disabled={loading}>
            {t.common.cancel}
          </Button>
          <Button onClick={handleCreate} disabled={loading || !name.trim() || !templateId}>
            {loading ? t.sandbox.create.creating : t.common.create}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
