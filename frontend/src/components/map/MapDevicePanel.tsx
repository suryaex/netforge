/**
 * MapDevicePanel — right-side properties panel for the selected map device.
 * Shows name, kind, coordinates, signal settings (txPower, frequency, range,
 * antennaHeight) and IP. Link quality info includes RSSI, rain fade, LOS status.
 */
import { Radio, Smartphone, RadioTower, MapPin, Signal, X, Mountain } from 'lucide-react';
import { useMapStore, calcRssi, rssiColor, type MapDeviceKind } from '@/store/mapStore';
import { cn } from '@/lib/cn';

const KIND_META: Record<MapDeviceKind, { label: string; icon: typeof Radio; color: string }> = {
  ap:    { label: 'Access Point',  icon: Radio,       color: '#5856D6' },
  cpe:   { label: 'CPE / Client',  icon: Smartphone,  color: '#007AFF' },
  tower: { label: 'Tower / Relay', icon: RadioTower,  color: '#FF9F0A' },
};

const LOS_BADGE: Record<string, { label: string; color: string }> = {
  clear:   { label: 'Clear ✓',    color: '#34C759' },
  partial: { label: 'Partial ⚠',  color: '#FFCC00' },
  blocked: { label: 'Blocked ✗',  color: '#FF453A' },
  unknown: { label: 'Unknown…',   color: '#8E8E93' },
};

export function MapDevicePanel() {
  const device = useMapStore((s) => s.selectedDevice());
  const updateDevice = useMapStore((s) => s.updateDevice);
  const selectDevice = useMapStore((s) => s.selectDevice);
  const links = useMapStore((s) => s.linkList());

  if (!device) return null;

  const meta = KIND_META[device.kind];
  const Icon = meta.icon;

  const myLinks = links.filter((l) => l.fromId === device.id || l.toId === device.id);
  const patch = (p: Parameters<typeof updateDevice>[1]) => updateDevice(device.id, p);

  return (
    <div className="pointer-events-auto absolute right-4 top-16 z-[1000] w-72 animate-fade-in">
      <div className="glass-strong overflow-hidden rounded-xl border border-white/15 shadow-glass-lg">
        {/* Header */}
        <div
          className="flex items-center gap-2.5 border-b border-white/10 px-4 py-3"
          style={{ background: `${meta.color}15` }}
        >
          <div
            className="grid h-9 w-9 shrink-0 place-items-center rounded-lg"
            style={{ background: `${meta.color}25`, color: meta.color }}
          >
            <Icon className="h-5 w-5" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold text-white/90">{device.name}</p>
            <p className="text-[10px] text-white/40">{meta.label}</p>
          </div>
          <button
            onClick={() => selectDevice(null)}
            aria-label="Close panel"
            className="grid h-6 w-6 place-items-center rounded-md text-white/40 hover:bg-white/10 hover:text-white"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>

        <div className="nf-scroll max-h-[calc(100vh-200px)] space-y-3 overflow-auto p-4">
          {/* Name */}
          <Field label="Name">
            <input
              value={device.name}
              onChange={(e) => patch({ name: e.target.value })}
              className="w-full rounded-md border border-white/10 bg-black/20 px-2.5 py-1.5 text-sm text-white/90 outline-none transition-colors focus:border-accent"
            />
          </Field>

          {/* Coordinates */}
          <div className="flex items-center gap-1.5 rounded-md bg-white/5 px-3 py-2">
            <MapPin className="h-3.5 w-3.5 shrink-0 text-white/40" />
            <span className="font-mono text-[11px] text-white/60">
              {device.lat.toFixed(6)}, {device.lng.toFixed(6)}
            </span>
          </div>

          {/* Signal Settings */}
          <section>
            <h4 className="mb-2 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-white/40">
              <Signal className="h-3 w-3" /> Signal Settings
            </h4>
            <div className="space-y-2.5">
              <Field label="TX Power (dBm)">
                <div className="flex items-center gap-2">
                  <input
                    type="range" min={0} max={33} step={1}
                    value={device.txPower}
                    onChange={(e) => patch({ txPower: Number(e.target.value) })}
                    className="flex-1 accent-accent"
                  />
                  <span className="w-8 text-right font-mono text-xs text-white/70">
                    {device.txPower}
                  </span>
                </div>
              </Field>

              <Field label="Frequency (GHz)">
                <select
                  value={device.frequency}
                  onChange={(e) => patch({ frequency: Number(e.target.value) })}
                  className="w-full rounded-md border border-white/10 bg-black/20 px-2 py-1.5 text-sm text-white/90 outline-none focus:border-accent"
                >
                  <option value={2.4}  className="bg-[#141A2E]">2.4 GHz</option>
                  <option value={5}    className="bg-[#141A2E]">5 GHz</option>
                  <option value={5.8}  className="bg-[#141A2E]">5.8 GHz</option>
                  <option value={24}   className="bg-[#141A2E]">24 GHz (fixed wireless)</option>
                  <option value={60}   className="bg-[#141A2E]">60 GHz (mmWave)</option>
                </select>
              </Field>

              <Field label="Coverage Radius (m)">
                <div className="flex items-center gap-2">
                  <input
                    type="range" min={50} max={5000} step={50}
                    value={device.range}
                    onChange={(e) => patch({ range: Number(e.target.value) })}
                    className="flex-1 accent-accent"
                  />
                  <span className="w-14 text-right font-mono text-xs text-white/70">
                    {device.range}m
                  </span>
                </div>
              </Field>
            </div>
          </section>

          {/* Antenna Height */}
          <section>
            <h4 className="mb-2 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-white/40">
              <Mountain className="h-3 w-3" /> Antenna Height (m AGL)
            </h4>
            <div className="flex items-center gap-2">
              <input
                type="range" min={1} max={100} step={1}
                value={device.antennaHeight}
                onChange={(e) => patch({ antennaHeight: Number(e.target.value) })}
                className="flex-1 accent-accent"
              />
              <span className="w-10 text-right font-mono text-xs text-white/70">
                {device.antennaHeight}m
              </span>
            </div>
          </section>

          {/* IP Address */}
          <Field label="IP Address">
            <input
              value={device.ip}
              onChange={(e) => patch({ ip: e.target.value })}
              placeholder="192.168.1.1/24"
              className="w-full rounded-md border border-white/10 bg-black/20 px-2.5 py-1.5 font-mono text-sm text-white/90 outline-none transition-colors focus:border-accent"
            />
          </Field>

          {/* Links & Signal Quality */}
          {myLinks.length > 0 && (
            <section>
              <h4 className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-white/40">
                Connected Links
              </h4>
              <ul className="space-y-1.5">
                {myLinks.map((l) => {
                  const effectiveRssi = l.rssi - l.obstructionDb;
                  const rc = rssiColor(effectiveRssi);
                  const losBadge = LOS_BADGE[l.los] ?? LOS_BADGE['unknown']!;
                  return (
                    <li
                      key={l.id}
                      className="space-y-1 rounded-md bg-white/5 px-2.5 py-2 text-xs"
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-white/60">{l.distance.toLocaleString()} m</span>
                        <span className="font-semibold" style={{ color: rc }}>
                          {effectiveRssi.toFixed(1)} dBm
                        </span>
                      </div>
                      {(l.rainDb > 0 || l.obstructionDb > 0) && (
                        <div className="text-[10px] text-white/40 space-y-0.5">
                          {l.rainDb > 0 && <p>Rain: −{l.rainDb.toFixed(1)} dB</p>}
                          {l.obstructionDb > 0 && <p>Terrain: −{l.obstructionDb.toFixed(1)} dB</p>}
                        </div>
                      )}
                      <div className="flex items-center justify-between">
                        <span className="text-white/35">Fresnel r₁: {l.fresnelM} m</span>
                        <span className="text-[10px] font-semibold" style={{ color: losBadge.color }}>
                          {losBadge.label}
                        </span>
                      </div>
                    </li>
                  );
                })}
              </ul>

              {/* Quick RSSI at range edge */}
              {device.kind !== 'cpe' && (
                <div className="mt-2 rounded-md bg-white/5 px-3 py-2 text-[11px] text-white/50">
                  Edge RSSI @ {device.range}m:{' '}
                  <span
                    className="font-semibold"
                    style={{ color: rssiColor(calcRssi(device.txPower, device.range, device.frequency)) }}
                  >
                    {calcRssi(device.txPower, device.range, device.frequency)} dBm
                  </span>
                </div>
              )}
            </section>
          )}
        </div>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className={cn('block space-y-1')}>
      <span className="text-[10px] font-medium uppercase tracking-wide text-white/40">{label}</span>
      {children}
    </label>
  );
}
