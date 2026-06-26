/**
 * DeviceLibraryModal — the flexible device-type manager for map mode.
 *
 * Surfaces the backend device-type registry (`/api/device-types`) and lets the
 * operator extend it three ways, UISP/EVE-NG style:
 *   1. Upload an appliance image (ISO/qcow2/img) → POST /api/device-types/upload
 *   2. Register a Docker image by name           → POST /api/device-types
 *   3. Enter a fully custom device manually      → POST /api/device-types
 *
 * Built-in types are read-only; custom types can be deleted. All network calls
 * surface first-class loading / error / empty states.
 */
import { useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Radio, Smartphone, RadioTower, Network, Router as RouterIcon, Server,
  Cloud, Shield, Boxes, Container, UploadCloud, Plus, Trash2, X, Loader2,
  AlertTriangle, CheckCircle2, type LucideIcon,
} from 'lucide-react';
import {
  deviceTypesApi,
  type DeviceType,
  type ApiError,
} from '@/api/client';
import { useMapStore } from '@/store/mapStore';
import { cn } from '@/lib/cn';

/* -------------------------------------------------------------------------- */
/* Icon + category mapping                                                     */
/* -------------------------------------------------------------------------- */
const ICON_MAP: Record<string, LucideIcon> = {
  ap: Radio,
  cpe: Smartphone,
  tower: RadioTower,
  switch: Network,
  router: RouterIcon,
  olt: Network,
  onu: Smartphone,
  fw: Shield,
  server: Server,
  cloud: Cloud,
  docker: Container,
};

function iconFor(dt: DeviceType): LucideIcon {
  return (dt.icon && ICON_MAP[dt.icon]) || Boxes;
}

const CATEGORY_COLOR: Record<string, string> = {
  wireless: '#5856D6',
  wired: '#007AFF',
  fiber: '#FF9F0A',
  security: '#FF453A',
  infrastructure: '#34C759',
  docker: '#2496ED',
  custom: '#8E8E93',
};

const catColor = (c: string) => CATEGORY_COLOR[c] ?? CATEGORY_COLOR.custom!;

type Tab = 'library' | 'upload' | 'docker' | 'manual';

/* -------------------------------------------------------------------------- */
/* Modal                                                                       */
/* -------------------------------------------------------------------------- */
export function DeviceLibraryModal() {
  const close = useMapStore((s) => s.closeDeviceLibrary);
  const [tab, setTab] = useState<Tab>('library');
  const qc = useQueryClient();

  const { data: types, isLoading, isError, error } = useQuery({
    queryKey: ['device-types'],
    queryFn: deviceTypesApi.list,
    staleTime: 30_000,
  });

  const invalidate = () => qc.invalidateQueries({ queryKey: ['device-types'] });

  const TABS: { key: Tab; label: string; icon: LucideIcon }[] = [
    { key: 'library', label: 'Library', icon: Boxes },
    { key: 'upload', label: 'Upload ISO', icon: UploadCloud },
    { key: 'docker', label: 'Docker', icon: Container },
    { key: 'manual', label: 'Custom', icon: Plus },
  ];

  return (
    <div
      className="fixed inset-0 z-[2000] flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm animate-fade-in"
      onClick={(e) => e.target === e.currentTarget && close()}
      role="dialog"
      aria-modal="true"
      aria-label="Device library"
    >
      <div className="glass-strong relative flex max-h-[80vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-white/15 shadow-glass-lg animate-scale-in">
        {/* Header */}
        <div className="flex items-center gap-3 border-b border-white/10 px-6 py-4">
          <div className="grid h-9 w-9 place-items-center rounded-lg bg-accent/20 text-accent">
            <Boxes className="h-5 w-5" />
          </div>
          <div className="flex-1">
            <h2 className="text-base font-semibold text-white">Device Library</h2>
            <p className="text-xs text-white/45">
              Built-in types plus your custom appliances, Docker images, and uploads.
            </p>
          </div>
          <button
            onClick={close}
            aria-label="Close device library"
            className="grid h-7 w-7 place-items-center rounded-md text-white/40 hover:bg-white/10 hover:text-white"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 border-b border-white/10 px-4 pt-3">
          {TABS.map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              className={cn(
                'flex items-center gap-1.5 rounded-t-lg px-3 py-2 text-xs font-medium transition-colors',
                tab === key
                  ? 'bg-white/10 text-white'
                  : 'text-white/45 hover:text-white/80',
              )}
            >
              <Icon className="h-3.5 w-3.5" />
              {label}
            </button>
          ))}
        </div>

        {/* Body */}
        <div className="nf-scroll min-h-[280px] flex-1 overflow-auto p-6">
          {tab === 'library' && (
            <DeviceTypeList
              types={types}
              isLoading={isLoading}
              isError={isError}
              error={error as ApiError | null}
              onChanged={invalidate}
            />
          )}
          {tab === 'upload' && <UploadIsoForm onDone={invalidate} />}
          {tab === 'docker' && <DockerForm onDone={invalidate} />}
          {tab === 'manual' && <ManualForm onDone={invalidate} />}
        </div>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Library list                                                                */
/* -------------------------------------------------------------------------- */
function DeviceTypeList({
  types, isLoading, isError, error, onChanged,
}: {
  types: DeviceType[] | undefined;
  isLoading: boolean;
  isError: boolean;
  error: ApiError | null;
  onChanged: () => void;
}) {
  const remove = useMutation({
    mutationFn: (id: string) => deviceTypesApi.remove(id),
    onSuccess: onChanged,
  });

  if (isLoading) {
    return (
      <div className="grid place-items-center py-16 text-white/40">
        <Loader2 className="h-6 w-6 animate-spin" />
        <p className="mt-2 text-xs">Loading device types…</p>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="grid place-items-center py-16 text-center text-danger/80">
        <AlertTriangle className="h-6 w-6" />
        <p className="mt-2 text-sm">Couldn’t load device types.</p>
        <p className="mt-1 text-xs text-white/40">{error?.message ?? 'Network error'}</p>
      </div>
    );
  }

  if (!types || types.length === 0) {
    return (
      <div className="grid place-items-center py-16 text-white/40">
        <Boxes className="h-6 w-6" />
        <p className="mt-2 text-sm">No device types yet.</p>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
      {types.map((dt) => {
        const Icon = iconFor(dt);
        const color = catColor(dt.category);
        return (
          <div
            key={dt.id}
            className="group relative flex flex-col gap-2 rounded-xl border border-white/10 bg-white/5 p-3 transition-colors hover:border-white/20"
          >
            <div
              className="grid h-9 w-9 place-items-center rounded-lg"
              style={{ background: `${color}22`, color }}
            >
              <Icon className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <p className="truncate text-sm font-medium text-white/90" title={dt.name}>
                {dt.name}
              </p>
              <p className="truncate text-[10px] uppercase tracking-wide text-white/35">
                {dt.category}
              </p>
            </div>
            {dt.builtin ? (
              <span className="absolute right-2 top-2 rounded bg-white/10 px-1.5 py-0.5 text-[8px] font-semibold uppercase tracking-wide text-white/40">
                Built-in
              </span>
            ) : (
              <button
                onClick={() => remove.mutate(dt.id)}
                disabled={remove.isPending}
                aria-label={`Delete ${dt.name}`}
                className="absolute right-1.5 top-1.5 grid h-6 w-6 place-items-center rounded-md text-white/30 opacity-0 transition-opacity hover:bg-danger/15 hover:text-danger group-hover:opacity-100"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Upload ISO form                                                             */
/* -------------------------------------------------------------------------- */
function UploadIsoForm({ onDone }: { onDone: () => void }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState('');
  const [pct, setPct] = useState(0);

  const upload = useMutation({
    mutationFn: () =>
      deviceTypesApi.uploadImage(file!, { name: name.trim() || undefined, onProgress: setPct }),
    onSuccess: () => {
      onDone();
      setFile(null);
      setName('');
      setPct(0);
      if (fileRef.current) fileRef.current.value = '';
    },
  });

  return (
    <form
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        if (file) upload.mutate();
      }}
    >
      <p className="text-xs leading-relaxed text-white/50">
        Upload an appliance image (<code className="text-white/70">.iso</code>,{' '}
        <code className="text-white/70">.qcow2</code>, <code className="text-white/70">.img</code>)
        to register it as a bootable device type.
      </p>

      <label
        className={cn(
          'flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border border-dashed px-4 py-8 text-center transition-colors',
          file ? 'border-accent/50 bg-accent/5' : 'border-white/20 hover:border-white/35 hover:bg-white/5',
        )}
      >
        <UploadCloud className="h-7 w-7 text-white/40" />
        {file ? (
          <span className="text-sm text-white/90">{file.name}</span>
        ) : (
          <span className="text-sm text-white/55">Click to choose an image file</span>
        )}
        <span className="text-[10px] text-white/35">
          {file ? `${(file.size / 1_048_576).toFixed(1)} MB` : 'ISO / qcow2 / img'}
        </span>
        <input
          ref={fileRef}
          type="file"
          accept=".iso,.qcow2,.img,.ova,.vmdk"
          className="hidden"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
      </label>

      <Field label="Display name (optional)">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. MikroTik CHR 7.x"
          className="w-full rounded-md border border-white/10 bg-black/20 px-2.5 py-1.5 text-sm text-white/90 outline-none focus:border-accent"
        />
      </Field>

      {upload.isPending && pct > 0 && (
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/10">
          <div className="h-full rounded-full bg-accent transition-all" style={{ width: `${pct}%` }} />
        </div>
      )}

      <FormStatus mutation={upload} successText="Image uploaded and registered." />

      <button
        type="submit"
        disabled={!file || upload.isPending}
        className="flex w-full items-center justify-center gap-2 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {upload.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <UploadCloud className="h-4 w-4" />}
        {upload.isPending ? 'Uploading…' : 'Upload & Register'}
      </button>
    </form>
  );
}

/* -------------------------------------------------------------------------- */
/* Docker form                                                                 */
/* -------------------------------------------------------------------------- */
function DockerForm({ onDone }: { onDone: () => void }) {
  const [image, setImage] = useState('');
  const [name, setName] = useState('');

  const create = useMutation({
    mutationFn: () => deviceTypesApi.fromDocker(image.trim(), name.trim() || undefined),
    onSuccess: () => {
      onDone();
      setImage('');
      setName('');
    },
  });

  return (
    <form
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        if (image.trim()) create.mutate();
      }}
    >
      <p className="text-xs leading-relaxed text-white/50">
        Register a device backed by a container image pulled from a registry.
      </p>

      <Field label="Docker image">
        <input
          value={image}
          onChange={(e) => setImage(e.target.value)}
          placeholder="e.g. frrouting/frr:latest"
          className="w-full rounded-md border border-white/10 bg-black/20 px-2.5 py-1.5 font-mono text-sm text-white/90 outline-none focus:border-accent"
        />
      </Field>

      <Field label="Display name (optional)">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Defaults to the image name"
          className="w-full rounded-md border border-white/10 bg-black/20 px-2.5 py-1.5 text-sm text-white/90 outline-none focus:border-accent"
        />
      </Field>

      <FormStatus mutation={create} successText="Docker device type added." />

      <button
        type="submit"
        disabled={!image.trim() || create.isPending}
        className="flex w-full items-center justify-center gap-2 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {create.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Container className="h-4 w-4" />}
        Add Docker Device
      </button>
    </form>
  );
}

/* -------------------------------------------------------------------------- */
/* Manual custom form                                                          */
/* -------------------------------------------------------------------------- */
function ManualForm({ onDone }: { onDone: () => void }) {
  const [name, setName] = useState('');
  const [category, setCategory] = useState('custom');
  const [description, setDescription] = useState('');

  const create = useMutation({
    mutationFn: () =>
      deviceTypesApi.create({ name: name.trim(), category, description: description.trim() }),
    onSuccess: () => {
      onDone();
      setName('');
      setDescription('');
      setCategory('custom');
    },
  });

  const CATEGORIES = ['custom', 'wireless', 'wired', 'fiber', 'security', 'infrastructure'];

  return (
    <form
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        if (name.trim()) create.mutate();
      }}
    >
      <Field label="Name">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Ubiquiti LiteBeam 5AC"
          className="w-full rounded-md border border-white/10 bg-black/20 px-2.5 py-1.5 text-sm text-white/90 outline-none focus:border-accent"
        />
      </Field>

      <Field label="Category">
        <select
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          className="w-full rounded-md border border-white/10 bg-black/20 px-2 py-1.5 text-sm text-white/90 outline-none focus:border-accent"
        >
          {CATEGORIES.map((c) => (
            <option key={c} value={c} className="bg-[#141A2E]">
              {c}
            </option>
          ))}
        </select>
      </Field>

      <Field label="Description (optional)">
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={3}
          placeholder="Notes about this device type…"
          className="w-full resize-none rounded-md border border-white/10 bg-black/20 px-2.5 py-1.5 text-sm text-white/90 outline-none focus:border-accent"
        />
      </Field>

      <FormStatus mutation={create} successText="Custom device type created." />

      <button
        type="submit"
        disabled={!name.trim() || create.isPending}
        className="flex w-full items-center justify-center gap-2 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {create.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
        Create Device Type
      </button>
    </form>
  );
}

/* -------------------------------------------------------------------------- */
/* Shared bits                                                                 */
/* -------------------------------------------------------------------------- */
function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1">
      <span className="text-[10px] font-medium uppercase tracking-wide text-white/40">{label}</span>
      {children}
    </label>
  );
}

function FormStatus({
  mutation,
  successText,
}: {
  mutation: { isError: boolean; isSuccess: boolean; error: unknown };
  successText: string;
}) {
  if (mutation.isError) {
    const err = mutation.error as ApiError | undefined;
    return (
      <p className="flex items-center gap-1.5 text-xs text-danger">
        <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
        {err?.message ?? 'Something went wrong.'}
      </p>
    );
  }
  if (mutation.isSuccess) {
    return (
      <p className="flex items-center gap-1.5 text-xs text-success">
        <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
        {successText}
      </p>
    );
  }
  return null;
}
