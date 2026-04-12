import { useState } from 'react';
import { Terminal } from 'lucide-react';
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
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import type { ExecCommandResponse } from '@/types/sandbox';

interface ExecCommandDialogProps {
  sandboxId: string;
  sandboxName: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

// 简单的命令解析（将字符串转换为数组）
const parseCommand = (command: string): string[] => {
  const trimmed = command.trim();
  if (!trimmed) return [];

  // 简单实现：按空格分割，支持引号
  const tokens: string[] = [];
  let current = '';
  let inQuote = false;
  let quoteChar = '';

  for (let i = 0; i < trimmed.length; i++) {
    const char = trimmed[i];

    if ((char === '"' || char === "'") && (!inQuote || char === quoteChar)) {
      if (inQuote) {
        inQuote = false;
        quoteChar = '';
      } else {
        inQuote = true;
        quoteChar = char;
      }
      continue;
    }

    if (char === ' ' && !inQuote) {
      if (current) {
        tokens.push(current);
        current = '';
      }
      continue;
    }

    current += char;
  }

  if (current) {
    tokens.push(current);
  }

  return tokens;
};

export function ExecCommandDialog({
  sandboxId,
  sandboxName,
  open,
  onOpenChange,
}: ExecCommandDialogProps) {
  const [command, setCommand] = useState('');
  const [result, setResult] = useState<ExecCommandResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { execCommand } = useSandboxStore();

  const handleExecute = async () => {
    setLoading(true);
    setError(null);

    try {
      const cmdArray = parseCommand(command);
      if (cmdArray.length === 0) {
        setError('Please enter a command');
        setLoading(false);
        return;
      }

      const response = await execCommand(sandboxId, cmdArray);
      setResult(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to execute command');
    } finally {
      setLoading(false);
    }
  };

  const handleClose = () => {
    setCommand('');
    setResult(null);
    setError(null);
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="max-w-3xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Terminal className="h-5 w-5" />
            Execute Command
          </DialogTitle>
          <DialogDescription>
            Execute a command in sandbox: {sandboxName}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="command">Command</Label>
            <Textarea
              id="command"
              value={command}
              onChange={(e) => setCommand(e.target.value)}
              placeholder={`python -c "print('Hello World')"`}
              rows={3}
              className="font-mono text-sm"
              disabled={loading}
            />
            <p className="text-xs text-muted-foreground">
              Example: <code>ls -la</code> or <code>python script.py</code>
            </p>
          </div>

          {error && (
            <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
              {error}
            </div>
          )}

          {result && (
            <div className="space-y-3 rounded-md border p-4">
              <div className="flex items-center justify-between">
                <Label>Exit Code: {result.exit_code}</Label>
                <span className="text-xs text-muted-foreground">
                  Execution time: {result.execution_time_ms}ms
                </span>
              </div>

              {result.stdout && (
                <div className="space-y-1">
                  <Label className="text-xs text-muted-foreground">Output (stdout)</Label>
                  <pre className="rounded-md bg-muted p-3 text-xs font-mono overflow-x-auto max-h-60">
                    {result.stdout}
                  </pre>
                </div>
              )}

              {result.stderr && (
                <div className="space-y-1">
                  <Label className="text-xs text-destructive">Error (stderr)</Label>
                  <pre className="rounded-md bg-destructive/10 p-3 text-xs font-mono overflow-x-auto max-h-40 text-destructive">
                    {result.stderr}
                  </pre>
                </div>
              )}

              {!result.stdout && !result.stderr && (
                <p className="text-sm text-muted-foreground italic">No output</p>
              )}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={handleClose}>
            Close
          </Button>
          <Button onClick={handleExecute} disabled={loading || !command.trim()}>
            {loading ? 'Executing...' : 'Execute'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
