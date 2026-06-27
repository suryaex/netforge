/**
 * DeviceNode — custom React Flow node renderer for a NetForge device.
 * Shows kind-colored glyph, name, NOS badge, sim/emul mode, and a live status
 * ring. Handles on all four sides allow link creation in any direction.
 * Memoized: with thousands of nodes, re-rendering only changed nodes matters.
 */
import { memo } from 'react';
import { Handle, Position, type NodeProps } from '@xyflow/react';
import {
  Router,
  Network,
  Monitor,
  Wifi,
  Cable,
  ShieldAlert,
  Server,
  Cloud,
} from 'lucide-react';
import type { NodeKind, NodeMode, NodeStatus, Nos } from '@/api/types';
import { nodeColors } from '@/theme/tokens';
import { cn } from '@/lib/cn';

export interface DeviceNodeData extends Record<string, unknown> {
  name: string;
  kind: NodeKind;
  nos: Nos;
  mode: NodeMode;
  status: NodeStatus;
}

const KIND_ICON: Record<NodeKind, typeof Router> = {
  router: Router,
  switch: Network,
  host: Monitor,
  ap: Wifi,
  olt: Cable,
  firewall: ShieldAlert,
  server: Server,
  cloud: Cloud,
};

const STATUS_RING: Record<NodeStatus, string> = {
  running: 'ring-success',
  booting: 'ring-warning animate-pulse',
  stopped: 'ring-white/20',
  degraded: 'ring-warning',
  error: 'ring-danger',
};

function DeviceNodeImpl({ data, selected }: NodeProps) {
  const d = data as DeviceNodeData;
  const Icon = KIND_ICON[d.kind];
  const color = nodeColors[d.kind];

  return (
    <div
      className={cn(
        'group relative flex w-[112px] flex-col items-center gap-1 rounded-md px-2 py-2',
        'glass border transition-shadow',
        selected ? 'border-accent shadow-glass' : 'border-white/10',
      )}
    >
      {(['top', 'right', 'bottom', 'left'] as const).map((side) => (
        <Handle
          key={side}
          type="source"
          position={Position[(side.charAt(0).toUpperCase() + side.slice(1)) as keyof typeof Position]}
          id={side}
          className="!h-2 !w-2"
        />
      ))}

      <div
        className={cn('grid h-10 w-10 place-items-center rounded-full ring-2', STATUS_RING[d.status])}
        style={{ background: `${color}22`, color }}
      >
        <Icon className="h-5 w-5" />
      </div>

      <span className="max-w-full truncate text-[12px] font-medium text-white/90">{d.name}</span>

      <div className="flex items-center gap-1">
        <span className="rounded bg-white/10 px-1 text-[9px] uppercase tracking-wide text-white/70">
          {d.nos}
        </span>
        <span
          className={cn(
            'rounded px-1 text-[9px] uppercase tracking-wide',
            d.mode === 'emul' ? 'bg-accent/30 text-accent-soft' : 'bg-white/10 text-white/60',
          )}
        >
          {d.mode}
        </span>
      </div>
    </div>
  );
}

export const DeviceNode = memo(DeviceNodeImpl);
