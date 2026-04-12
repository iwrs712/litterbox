import { Badge } from '@/components/ui/badge';
import type { SandboxStatus } from '@/types/sandbox';

interface SandboxStatusBadgeProps {
  status: SandboxStatus;
}

const statusVariants: Record<
  SandboxStatus,
  { variant: 'default' | 'secondary' | 'destructive' | 'outline'; label: string }
> = {
  created: { variant: 'outline', label: 'Created' },
  creating: { variant: 'outline', label: 'Creating' },
  running: { variant: 'default', label: 'Running' },
  stopped: { variant: 'secondary', label: 'Stopped' },
  exited: { variant: 'secondary', label: 'Exited' },
  unknown: { variant: 'outline', label: 'Unknown' },
  pooled: { variant: 'outline', label: 'Pooled' },
};

export function SandboxStatusBadge({ status }: SandboxStatusBadgeProps) {
  const { variant, label } = statusVariants[status] || {
    variant: 'outline',
    label: status,
  };

  return <Badge variant={variant}>{label}</Badge>;
}
