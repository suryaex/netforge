/**
 * MapOnboardingModal — welcome modal for the satellite map mode.
 * Mirrors the UISP Design Center "Start a network" prompt.
 * Three quickstart options: multi-point AP network, P2P bridge, fiber.
 */
import { Radio, ArrowRightLeft, Cable, X } from 'lucide-react';
import { useMapStore, type MapTool } from '@/store/mapStore';
import { cn } from '@/lib/cn';

interface QuickstartOption {
  icon: typeof Radio;
  color: string;
  title: string;
  description: string;
  tool: MapTool;
}

const OPTIONS: QuickstartOption[] = [
  {
    icon: Radio,
    color: '#5856D6',
    title: 'Multi-Point Network',
    description: 'Place an Access Point, then add CPE clients. Links and signal coverage drawn automatically.',
    tool: 'ap',
  },
  {
    icon: ArrowRightLeft,
    color: '#007AFF',
    title: 'Point-to-Point Bridge',
    description: 'Place two Towers for a directional backhaul link with RSSI estimation.',
    tool: 'tower',
  },
  {
    icon: Cable,
    color: '#FF9F0A',
    title: 'Custom Placement',
    description: 'Use the toolbar to freely mix Access Points, CPEs, and Towers on the map.',
    tool: 'select',
  },
];

export function MapOnboardingModal() {
  const dismiss = useMapStore((s) => s.dismissOnboarding);
  const setTool = useMapStore((s) => s.setTool);

  const pick = (opt: QuickstartOption) => {
    setTool(opt.tool);
    dismiss();
  };

  return (
    <div
      className="fixed inset-0 z-[2000] flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in"
      onClick={(e) => e.target === e.currentTarget && dismiss()}
    >
      <div className="glass-strong relative w-full max-w-lg overflow-hidden rounded-2xl border border-white/15 shadow-glass-lg animate-scale-in">
        {/* Close */}
        <button
          onClick={dismiss}
          aria-label="Skip onboarding"
          className="absolute right-4 top-4 grid h-7 w-7 place-items-center rounded-md text-white/40 hover:bg-white/10 hover:text-white"
        >
          <X className="h-4 w-4" />
        </button>

        {/* Header */}
        <div className="border-b border-white/10 px-8 pb-5 pt-8 text-center">
          <div className="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-xl bg-accent/20 text-accent">
            <Radio className="h-6 w-6" />
          </div>
          <h2 className="text-lg font-semibold text-white">Start a Network Design</h2>
          <p className="mt-1 text-sm text-white/55">
            Click the map to place devices. Links and signal coverage are drawn automatically.
          </p>
        </div>

        {/* Options */}
        <div className="grid gap-3 p-6">
          {OPTIONS.map((opt) => {
            const Icon = opt.icon;
            return (
              <button
                key={opt.title}
                onClick={() => pick(opt)}
                className={cn(
                  'group flex items-center gap-4 rounded-xl border border-white/10 bg-white/5 p-4 text-left',
                  'transition-all duration-fast hover:border-white/20 hover:bg-white/10',
                )}
              >
                <div
                  className="grid h-10 w-10 shrink-0 place-items-center rounded-lg transition-transform group-hover:scale-110"
                  style={{ background: `${opt.color}22`, color: opt.color }}
                >
                  <Icon className="h-5 w-5" />
                </div>
                <div>
                  <p className="font-medium text-white/90">{opt.title}</p>
                  <p className="mt-0.5 text-xs leading-relaxed text-white/50">{opt.description}</p>
                </div>
              </button>
            );
          })}
        </div>

        <div className="border-t border-white/10 px-6 py-3 text-center">
          <button
            onClick={dismiss}
            className="text-xs text-white/35 hover:text-white/60 transition-colors"
          >
            Skip — I'll explore on my own
          </button>
        </div>
      </div>
    </div>
  );
}
