import { Badge } from '@/components/ui/badge';
import type { VMStatus } from '@/types/vm';

interface VMStatusBadgeProps {
  status: VMStatus;
}

export function VMStatusBadge({ status }: VMStatusBadgeProps) {
  const variants = {
    running: { variant: 'success' as const, label: 'Running' },
    paused: { variant: 'warning' as const, label: 'Paused' },
    stopped: { variant: 'secondary' as const, label: 'Stopped' },
    failed: { variant: 'destructive' as const, label: 'Failed' },
    created: { variant: 'outline' as const, label: 'Created' },
    ready: { variant: 'outline' as const, label: 'Ready' },
  };

  const config = variants[status] || variants.stopped;

  return <Badge variant={config.variant}>{config.label}</Badge>;
}
