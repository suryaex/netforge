/**
 * SettingsPanel — application settings window.
 * Sections:
 *   1. General — theme, simulation defaults
 *   2. Network OS — manage built-in NOS list + add custom NOS/images
 *   3. Account — username display, sign-out
 */
import { useState } from 'react';
import {
  Cpu,
  LogOut,
  Moon,
  Plus,
  Sun,
  Trash2,
  Monitor,
  Package,
  ChevronDown,
  Radio,
} from 'lucide-react';
import { useUiStore } from '@/store/uiStore';
import { useAuthStore } from '@/store/authStore';
import { useNosStore, type CustomNosEntry } from '@/store/nosStore';
import { cn } from '@/lib/cn';

type Section = 'general' | 'nos' | 'devices' | 'account';

const SECTIONS: { key: Section; label: string; icon: typeof Cpu }[] = [
  { key: 'general', label: 'General', icon: Monitor },
  { key: 'nos', label: 'Network OS', icon: Package },
  { key: 'devices', label: 'Device Types', icon: Radio },
  { key: 'account', label: 'Account', icon: Cpu },
];

/** Built-in NOS list (read-only display). */
const BUILTIN_NOS = [
  { key: 'forgeos', label: 'ForgeOS', description: 'Native simulation NOS' },
  { key: 'ios', label: 'Cisco IOS', description: 'Classic IOS CLI' },
  { key: 'iosxr', label: 'Cisco IOS-XR', description: 'Service-provider grade' },
  { key: 'nxos', label: 'Cisco NX-OS', description: 'Datacenter switching' },
  { key: 'junos', label: 'Juniper JunOS', description: 'Junos platform' },
  { key: 'eos', label: 'Arista EOS', description: 'Arista Extensible OS' },
  { key: 'routeros', label: 'MikroTik RouterOS', description: 'Embedded router OS' },
  { key: 'vyos', label: 'VyOS', description: 'Open-source network OS' },
  { key: 'sros', label: 'Nokia SR-OS', description: 'Service Router OS' },
  { key: 'frr', label: 'FRRouting (FRR)', description: 'Free Range Routing daemon' },
  { key: 'vrp', label: 'Huawei VRP', description: 'Versatile Routing Platform' },
];

export function SettingsPanel() {
  const [activeSection, setActiveSection] = useState<Section>('general');

  return (
    <div className="flex h-full">
      {/* Sidebar */}
      <nav className="w-40 shrink-0 border-r border-white/10 py-3">
        {SECTIONS.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            onClick={() => setActiveSection(key)}
            className={cn(
              'flex w-full items-center gap-2.5 px-4 py-2.5 text-left text-sm transition-colors',
              activeSection === key
                ? 'bg-accent/15 font-medium text-accent'
                : 'text-white/60 hover:bg-white/5 hover:text-white/85',
            )}
          >
            <Icon className="h-4 w-4 shrink-0" />
            {label}
          </button>
        ))}
      </nav>

      {/* Content */}
      <div className="nf-scroll min-h-0 flex-1 overflow-auto p-5">
        {activeSection === 'general' && <GeneralSection />}
        {activeSection === 'nos' && <NosSection />}
        {activeSection === 'devices' && <DeviceTypesSection />}
        {activeSection === 'account' && <AccountSection />}
      </div>
    </div>
  );
}

/* ---------- General ---------- */

function GeneralSection() {
  const theme = useUiStore((s) => s.theme);
  const setTheme = useUiStore((s) => s.setTheme);
  const simSpeed = useUiStore((s) => s.simSpeed);
  const setSimSpeed = useUiStore((s) => s.setSimSpeed);

  return (
    <div className="space-y-6">
      <SectionHeading>Appearance</SectionHeading>

      <Row label="Theme" description="Choose between dark and light interface.">
        <div className="flex gap-2">
          {(['dark', 'light'] as const).map((m) => (
            <button
              key={m}
              onClick={() => setTheme(m)}
              className={cn(
                'flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs transition-colors',
                theme === m
                  ? 'border-accent bg-accent/15 text-accent'
                  : 'border-white/10 bg-white/5 text-white/60 hover:border-white/20 hover:text-white/85',
              )}
            >
              {m === 'dark' ? <Moon className="h-3.5 w-3.5" /> : <Sun className="h-3.5 w-3.5" />}
              {m.charAt(0).toUpperCase() + m.slice(1)}
            </button>
          ))}
        </div>
      </Row>

      <SectionHeading>Simulation</SectionHeading>

      <Row label="Default speed" description="Simulation speed multiplier applied on play.">
        <div className="relative">
          <select
            value={simSpeed}
            onChange={(e) => setSimSpeed(Number(e.target.value))}
            className="appearance-none rounded-md border border-white/10 bg-black/25 py-1.5 pl-3 pr-8 text-sm text-white/90 outline-none focus:border-accent"
          >
            {[0.5, 1, 2, 4, 8].map((s) => (
              <option key={s} value={s} className="bg-[#141A2E]">
                {s}×
              </option>
            ))}
          </select>
          <ChevronDown className="pointer-events-none absolute right-2 top-1/2 h-4 w-4 -translate-y-1/2 text-white/40" />
        </div>
      </Row>

      <SectionHeading>About</SectionHeading>
      <div className="rounded-lg border border-white/10 bg-white/5 px-4 py-3 text-sm text-white/60">
        <p className="font-medium text-white/80">NetForge v0.1.0</p>
        <p className="mt-0.5 text-xs">Network Simulation Platform — React + FastAPI</p>
      </div>
    </div>
  );
}

/* ---------- Network OS ---------- */

function NosSection() {
  const { customNos, addNos, removeNos } = useNosStore();
  const [showForm, setShowForm] = useState(false);

  const [formKey, setFormKey] = useState('');
  const [formLabel, setFormLabel] = useState('');
  const [formImage, setFormImage] = useState('');
  const [formDesc, setFormDesc] = useState('');

  const handleAdd = () => {
    if (!formLabel.trim()) return;
    addNos({
      key: formKey.trim() || undefined,
      label: formLabel.trim(),
      dockerImage: formImage.trim() || undefined,
      description: formDesc.trim() || undefined,
    });
    setFormKey('');
    setFormLabel('');
    setFormImage('');
    setFormDesc('');
    setShowForm(false);
  };

  return (
    <div className="space-y-6">
      <SectionHeading>Built-in Network Operating Systems</SectionHeading>
      <p className="text-xs text-white/45">
        These NOS entries are built into NetForge and cannot be removed.
      </p>

      <div className="space-y-1.5">
        {BUILTIN_NOS.map((n) => (
          <div
            key={n.key}
            className="flex items-center justify-between rounded-md border border-white/8 bg-white/5 px-3 py-2"
          >
            <div>
              <p className="text-sm font-medium text-white/85">{n.label}</p>
              <p className="text-xs text-white/40">{n.description}</p>
            </div>
            <span className="rounded bg-white/8 px-1.5 py-0.5 font-mono text-[10px] text-white/50">
              {n.key}
            </span>
          </div>
        ))}
      </div>

      <div className="flex items-center justify-between">
        <SectionHeading>Custom Network OS</SectionHeading>
        <button
          onClick={() => setShowForm((v) => !v)}
          className="flex items-center gap-1.5 rounded-md border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-white/70 transition-colors hover:border-accent/50 hover:text-accent"
        >
          <Plus className="h-3.5 w-3.5" />
          Add NOS
        </button>
      </div>

      {/* Add form */}
      {showForm && (
        <div className="space-y-3 rounded-lg border border-accent/20 bg-accent/5 p-4">
          <h3 className="text-sm font-medium text-white/80">New Network OS</h3>
          <div className="grid grid-cols-2 gap-3">
            <FormField label="Label *" hint="e.g. OpenWRT 23.05">
              <input
                value={formLabel}
                onChange={(e) => setFormLabel(e.target.value)}
                placeholder="OpenWRT 23.05"
                className={inputCls}
              />
            </FormField>
            <FormField label="Key (slug)" hint="Auto-generated if blank">
              <input
                value={formKey}
                onChange={(e) => setFormKey(e.target.value)}
                placeholder="openwrt-23"
                className={inputCls}
              />
            </FormField>
          </div>
          <FormField label="Docker image / ISO" hint="Optional — used by the emulation engine">
            <input
              value={formImage}
              onChange={(e) => setFormImage(e.target.value)}
              placeholder="openwrt/openwrt:23.05"
              className={inputCls}
            />
          </FormField>
          <FormField label="Description" hint="Short note shown in dropdowns">
            <input
              value={formDesc}
              onChange={(e) => setFormDesc(e.target.value)}
              placeholder="Embedded Linux router OS"
              className={inputCls}
            />
          </FormField>
          <div className="flex justify-end gap-2 pt-1">
            <button
              onClick={() => setShowForm(false)}
              className="rounded-md px-3 py-1.5 text-sm text-white/50 hover:text-white/80"
            >
              Cancel
            </button>
            <button
              onClick={handleAdd}
              disabled={!formLabel.trim()}
              className={cn(
                'rounded-md px-4 py-1.5 text-sm font-medium text-white transition-colors',
                formLabel.trim()
                  ? 'bg-accent hover:bg-accent-soft'
                  : 'cursor-not-allowed bg-accent/40',
              )}
            >
              Add
            </button>
          </div>
        </div>
      )}

      {customNos.length === 0 ? (
        <p className="rounded-md border border-dashed border-white/10 p-4 text-center text-xs text-white/35">
          No custom NOS entries yet. Click "Add NOS" to define one.
        </p>
      ) : (
        <div className="space-y-1.5">
          {customNos.map((entry) => (
            <CustomNosRow key={entry.key} entry={entry} onRemove={() => removeNos(entry.key)} />
          ))}
        </div>
      )}
    </div>
  );
}

function CustomNosRow({ entry, onRemove }: { entry: CustomNosEntry; onRemove: () => void }) {
  return (
    <div className="flex items-start justify-between rounded-md border border-white/10 bg-white/5 px-3 py-2">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <p className="text-sm font-medium text-white/85">{entry.label}</p>
          <span className="rounded bg-accent/15 px-1.5 py-0.5 font-mono text-[10px] text-accent">
            {entry.key}
          </span>
        </div>
        {entry.description && (
          <p className="mt-0.5 text-xs text-white/40">{entry.description}</p>
        )}
        {entry.dockerImage && (
          <p className="mt-0.5 font-mono text-[10px] text-white/30">{entry.dockerImage}</p>
        )}
      </div>
      <button
        onClick={onRemove}
        aria-label={`Remove ${entry.label}`}
        className="ml-2 mt-0.5 shrink-0 rounded p-1 text-white/30 transition-colors hover:bg-danger/15 hover:text-danger"
      >
        <Trash2 className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

/* ---------- Device Types (Map mode) ---------- */

interface CustomDeviceType {
  id: string;
  name: string;
  kind: 'iso' | 'docker' | 'manual';
  source: string;      // Docker image name or ISO path
  description?: string;
  createdAt: string;
}

const DEVICE_TYPES_KEY = 'netforge.deviceTypes';

function loadDeviceTypes(): CustomDeviceType[] {
  try {
    const raw = localStorage.getItem(DEVICE_TYPES_KEY);
    return raw ? (JSON.parse(raw) as CustomDeviceType[]) : [];
  } catch {
    return [];
  }
}

function saveDeviceTypes(list: CustomDeviceType[]): void {
  localStorage.setItem(DEVICE_TYPES_KEY, JSON.stringify(list));
}

function DeviceTypesSection() {
  const [types, setTypes] = useState<CustomDeviceType[]>(loadDeviceTypes);
  const [showForm, setShowForm] = useState(false);
  const [kind, setKind] = useState<CustomDeviceType['kind']>('docker');
  const [name, setName] = useState('');
  const [source, setSource] = useState('');
  const [desc, setDesc] = useState('');

  const add = () => {
    if (!name.trim()) return;
    const entry: CustomDeviceType = {
      id: `dt-${Date.now()}`,
      name: name.trim(),
      kind,
      source: source.trim(),
      description: desc.trim() || undefined,
      createdAt: new Date().toISOString(),
    };
    const updated = [...types, entry];
    setTypes(updated);
    saveDeviceTypes(updated);
    setName(''); setSource(''); setDesc('');
    setShowForm(false);
  };

  const remove = (id: string) => {
    const updated = types.filter((t) => t.id !== id);
    setTypes(updated);
    saveDeviceTypes(updated);
  };

  const kindMeta: Record<CustomDeviceType['kind'], { label: string; placeholder: string; hint: string }> = {
    docker: {
      label: 'Docker Image',
      placeholder: 'vyos/vyos:1.4-rolling-202401',
      hint: 'Any Docker Hub or private registry image',
    },
    iso: {
      label: 'ISO / Appliance Path',
      placeholder: '/opt/images/mikrotik-chr-7.12.img',
      hint: 'Path to qcow2 / ISO / vmdk on the server',
    },
    manual: {
      label: 'Identifier (optional)',
      placeholder: 'custom-device-v1',
      hint: 'Manual entry — no image required',
    },
  };

  const kindColor: Record<CustomDeviceType['kind'], string> = {
    docker: '#007AFF',
    iso:    '#FF9F0A',
    manual: '#34C759',
  };

  return (
    <div className="space-y-5">
      <SectionHeading>Custom Device Types</SectionHeading>
      <p className="text-xs text-white/45">
        Register network device types for use in map-mode emulation. Sources can be
        Docker images, local appliance images (ISO / qcow2), or manual entries.
      </p>

      <div className="flex items-center justify-between">
        <span className="text-xs text-white/50">{types.length} custom type{types.length !== 1 ? 's' : ''}</span>
        <button
          onClick={() => setShowForm((v) => !v)}
          className="flex items-center gap-1.5 rounded-md border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-white/70 transition-colors hover:border-accent/50 hover:text-accent"
        >
          <Plus className="h-3.5 w-3.5" />
          Add Device Type
        </button>
      </div>

      {showForm && (
        <div className="space-y-3 rounded-lg border border-accent/20 bg-accent/5 p-4">
          <h3 className="text-sm font-medium text-white/80">New Device Type</h3>

          {/* Kind selector */}
          <div className="flex rounded-md border border-white/10 bg-black/20 p-0.5">
            {(['docker', 'iso', 'manual'] as const).map((k) => (
              <button
                key={k}
                onClick={() => setKind(k)}
                className={cn(
                  'flex-1 rounded px-2 py-1 text-xs capitalize transition-colors',
                  kind === k
                    ? 'text-white'
                    : 'text-white/50 hover:text-white/80',
                )}
                style={kind === k ? { background: `${kindColor[k]}30`, color: kindColor[k] } : undefined}
              >
                {k}
              </button>
            ))}
          </div>

          <FormField label="Name *">
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. VyOS 1.4 Router"
              className={inputCls}
            />
          </FormField>

          <FormField label={kindMeta[kind].label} hint={kindMeta[kind].hint}>
            <input
              value={source}
              onChange={(e) => setSource(e.target.value)}
              placeholder={kindMeta[kind].placeholder}
              className={inputCls}
            />
          </FormField>

          <FormField label="Description (optional)">
            <input
              value={desc}
              onChange={(e) => setDesc(e.target.value)}
              placeholder="Short description…"
              className={inputCls}
            />
          </FormField>

          <div className="flex justify-end gap-2 pt-1">
            <button
              onClick={() => setShowForm(false)}
              className="rounded-md px-3 py-1.5 text-sm text-white/50 hover:text-white/80"
            >
              Cancel
            </button>
            <button
              onClick={add}
              disabled={!name.trim()}
              className={cn(
                'rounded-md px-4 py-1.5 text-sm font-medium text-white transition-colors',
                name.trim() ? 'bg-accent hover:bg-accent-soft' : 'cursor-not-allowed bg-accent/40',
              )}
            >
              Add
            </button>
          </div>
        </div>
      )}

      {types.length === 0 ? (
        <p className="rounded-md border border-dashed border-white/10 p-4 text-center text-xs text-white/35">
          No custom device types yet.
        </p>
      ) : (
        <div className="space-y-1.5">
          {types.map((t) => (
            <div
              key={t.id}
              className="flex items-start justify-between rounded-md border border-white/10 bg-white/5 px-3 py-2"
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <p className="text-sm font-medium text-white/85">{t.name}</p>
                  <span
                    className="rounded px-1.5 py-0.5 text-[10px] capitalize"
                    style={{ background: `${kindColor[t.kind]}20`, color: kindColor[t.kind] }}
                  >
                    {t.kind}
                  </span>
                </div>
                {t.description && (
                  <p className="mt-0.5 text-xs text-white/40">{t.description}</p>
                )}
                {t.source && (
                  <p className="mt-0.5 font-mono text-[10px] text-white/30 truncate">{t.source}</p>
                )}
              </div>
              <button
                onClick={() => remove(t.id)}
                aria-label={`Remove ${t.name}`}
                className="ml-2 shrink-0 rounded p-1 text-white/30 hover:bg-danger/15 hover:text-danger"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
        </div>
      )}

      <SectionHeading>Built-in Wireless Device Templates</SectionHeading>
      <p className="text-xs text-white/45">
        Default device types available in map mode. These cannot be removed.
      </p>
      {[
        { name: 'Access Point (Generic)', desc: 'Wi-Fi AP — 5 GHz, 20 dBm, 500 m range' },
        { name: 'CPE / Client Device', desc: 'Customer Premises Equipment — auto-links to nearest AP' },
        { name: 'Backhaul Tower', desc: 'Long-range tower — 5 GHz, 27 dBm, 2 km range' },
      ].map((t) => (
        <div
          key={t.name}
          className="flex items-center justify-between rounded-md border border-white/8 bg-white/5 px-3 py-2"
        >
          <div>
            <p className="text-sm font-medium text-white/75">{t.name}</p>
            <p className="text-xs text-white/35">{t.desc}</p>
          </div>
          <span className="rounded bg-white/8 px-1.5 py-0.5 text-[10px] text-white/40">built-in</span>
        </div>
      ))}
    </div>
  );
}

/* ---------- Account ---------- */

function AccountSection() {
  const username = useAuthStore((s) => s.username);
  const logout = useAuthStore((s) => s.logout);

  return (
    <div className="space-y-6">
      <SectionHeading>Signed-in account</SectionHeading>

      <div className="flex items-center gap-4 rounded-lg border border-white/10 bg-white/5 px-4 py-3">
        <div className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-accent/20 text-lg font-semibold text-accent">
          {username?.[0]?.toUpperCase() ?? '?'}
        </div>
        <div>
          <p className="font-medium text-white/90">{username}</p>
          <p className="text-xs text-white/40">Local account</p>
        </div>
      </div>

      <button
        onClick={logout}
        className="flex items-center gap-2 rounded-md border border-danger/30 bg-danger/10 px-4 py-2.5 text-sm text-danger transition-colors hover:bg-danger/20"
      >
        <LogOut className="h-4 w-4" />
        Sign out
      </button>
    </div>
  );
}

/* ---------- Shared helpers ---------- */

const inputCls =
  'w-full rounded-md border border-white/10 bg-black/25 px-3 py-1.5 text-sm text-white/90 outline-none transition-colors focus:border-accent placeholder:text-white/25';

function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="text-[11px] font-semibold uppercase tracking-wider text-white/45">{children}</h3>
  );
}

function Row({
  label,
  description,
  children,
}: {
  label: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div className="min-w-0">
        <p className="text-sm text-white/80">{label}</p>
        {description && <p className="mt-0.5 text-xs text-white/40">{description}</p>}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}

function FormField({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1">
      <label className="block text-[11px] font-medium uppercase tracking-wide text-white/45">
        {label}
      </label>
      {children}
      {hint && <p className="text-[10px] text-white/30">{hint}</p>}
    </div>
  );
}
