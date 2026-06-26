/**
 * MapToolbar — left-side vertical toolbar for the satellite map view.
 * Tools: Select, Place AP, Place CPE, Place Tower, Measure Distance.
 * Matches the UISP Design Center sidebar aesthetic.
 */
import { MousePointer2, Radio, Smartphone, RadioTower, Ruler, Trash2 } from 'lucide-react';
import { useMapStore, type MapTool } from '@/store/mapStore';
import { cn } from '@/lib/cn';

interface ToolItem {
  tool: MapTool;
  icon: typeof MousePointer2;
  label: string;
  color: string;
}

const TOOLS: ToolItem[] = [
  { tool: 'select', icon: MousePointer2, label: 'Select', color: '#8E8E93' },
  { tool: 'ap', icon: Radio, label: 'Place Access Point', color: '#5856D6' },
  { tool: 'cpe', icon: Smartphone, label: 'Place CPE / Client', color: '#007AFF' },
  { tool: 'tower', icon: RadioTower, label: 'Place Tower', color: '#FF9F0A' },
  { tool: 'measure', icon: Ruler, label: 'Measure Distance', color: '#34C759' },
];

export function MapToolbar() {
  const tool = useMapStore((s) => s.tool);
  const setTool = useMapStore((s) => s.setTool);
  const selectedId = useMapStore((s) => s.selectedDeviceId);
  const removeDevice = useMapStore((s) => s.removeDevice);
  const selectDevice = useMapStore((s) => s.selectDevice);

  const handleDelete = () => {
    if (selectedId) {
      removeDevice(selectedId);
      selectDevice(null);
    }
  };

  return (
    <div className="pointer-events-auto absolute left-4 top-1/2 z-[1000] -translate-y-1/2">
      <div className="glass-strong flex flex-col gap-1 rounded-xl border border-white/15 p-1.5 shadow-glass-lg">
        {TOOLS.map(({ tool: t, icon: Icon, label, color }) => (
          <button
            key={t}
            onClick={() => setTool(t)}
            title={label}
            aria-label={label}
            aria-pressed={tool === t}
            className={cn(
              'group relative grid h-10 w-10 place-items-center rounded-lg transition-all duration-fast',
              tool === t
                ? 'shadow-lg'
                : 'text-white/50 hover:bg-white/10 hover:text-white',
            )}
            style={
              tool === t
                ? { background: `${color}25`, color, boxShadow: `0 4px 16px ${color}40` }
                : undefined
            }
          >
            <Icon className="h-5 w-5" />
            {/* Tooltip */}
            <span className="pointer-events-none absolute left-[calc(100%+8px)] top-1/2 -translate-y-1/2 whitespace-nowrap rounded-md bg-black/80 px-2 py-1 text-[11px] text-white/90 opacity-0 transition-opacity group-hover:opacity-100">
              {label}
            </span>
          </button>
        ))}

        {/* Separator + Delete */}
        <div className="my-0.5 border-t border-white/10" />
        <button
          onClick={handleDelete}
          title="Delete selected device"
          aria-label="Delete selected device"
          disabled={!selectedId}
          className={cn(
            'grid h-10 w-10 place-items-center rounded-lg transition-all duration-fast',
            selectedId
              ? 'text-danger/80 hover:bg-danger/10 hover:text-danger'
              : 'cursor-not-allowed text-white/20',
          )}
        >
          <Trash2 className="h-5 w-5" />
        </button>
      </div>
    </div>
  );
}
