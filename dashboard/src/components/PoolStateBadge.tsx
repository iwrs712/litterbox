import { Badge } from '@/components/ui/badge';
import type { PoolState } from '@/types/sandbox';

interface PoolStateBadgeProps {
  poolState: PoolState;
}

const poolStateVariants: Record<
  PoolState,
  { variant: 'default' | 'secondary' | 'destructive' | 'outline'; label: string }
> = {
  none: { variant: 'outline', label: 'Direct' },
  creating: { variant: 'default', label: 'Creating' },
  available: { variant: 'default', label: 'Available' },
  allocated: { variant: 'secondary', label: 'Allocated' },
  failed: { variant: 'destructive', label: 'Failed' },
};

export function PoolStateBadge({ poolState }: PoolStateBadgeProps) {
  const { variant, label } = poolStateVariants[poolState] || {
    variant: 'outline',
    label: poolState,
  };

  return <Badge variant={variant}>{label}</Badge>;
}
