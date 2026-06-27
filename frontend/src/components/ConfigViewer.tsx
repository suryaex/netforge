/**
 * ConfigViewer — shows generated config artifacts for a node (MASTER_SPEC §4
 * ConfigArtifact). Tabs per vendor/format, copy-to-clipboard, regenerate.
 * Demonstrates the ForgeOS "one intent → many target NOS" output (§5): the
 * same node can render IOS/Junos/RouterOS side by side.
 *
 * Heavy syntax highlighting is intentionally deferred (kept as a <pre> with
 * mono font) to protect the bundle/RAM budget; a lazy highlighter can be
 * dropped in later behind a dynamic import.
 */
import { useEffect, useState } from 'react';
import { Check, Copy, FileCode2, RefreshCw } from 'lucide-react';
import { configsApi } from '@/api/client';
import { useTopologyStore } from '@/store/topologyStore';
import type { ConfigArtifact } from '@/api/types';
import type { WindowInstance } from '@/store/windowStore';
import { cn } from '@/lib/cn';

export function ConfigViewer({ win }: { win: WindowInstance }) {
  const selectedId = useTopologyStore((s) => s.selectedNodeId);
  const nodeId = win.context?.nodeId ?? selectedId;

  const [artifacts, setArtifacts] = useState<ConfigArtifact[]>([]);
  const [active, setActive] = useState(0);
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!nodeId) return;
    setActive(0);
    setLoading(true);
    setError(null);
    configsApi
      .forNode(nodeId)
      .then((a) => setArtifacts(a))
      .catch((e) => setError(e?.message ?? 'Failed to load configs'))
      .finally(() => setLoading(false));
  }, [nodeId]);

  if (!nodeId) {
    return (
      <Empty>Select a node, then open Config Viewer to see generated output.</Empty>
    );
  }

  const regenerate = () => {
    setLoading(true);
    configsApi
      .generate(nodeId)
      .then((a) => setArtifacts((prev) => [a, ...prev]))
      .catch((e) => setError(e?.message ?? 'Generation failed'))
      .finally(() => setLoading(false));
  };

  const current = artifacts[active];
  const copy = () => {
    if (!current) return;
    void navigator.clipboard.writeText(current.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 1200);
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-white/10 px-2 py-1.5">
        <div className="nf-scroll flex flex-1 gap-1 overflow-x-auto">
          {artifacts.map((a, i) => (
            <button
              key={a.id}
              onClick={() => setActive(i)}
              className={cn(
                'shrink-0 rounded-md px-2 py-1 text-xs',
                i === active ? 'bg-accent text-white' : 'bg-white/5 text-white/60 hover:bg-white/10',
              )}
            >
              {a.vendor} · {a.format}
            </button>
          ))}
        </div>
        <button
          onClick={copy}
          disabled={!current}
          aria-label="Copy config"
          className="grid h-7 w-7 place-items-center rounded text-white/70 hover:bg-white/10 disabled:opacity-40"
        >
          {copied ? <Check className="h-4 w-4 text-success" /> : <Copy className="h-4 w-4" />}
        </button>
        <button
          onClick={regenerate}
          aria-label="Regenerate config"
          className="grid h-7 w-7 place-items-center rounded text-white/70 hover:bg-white/10"
        >
          <RefreshCw className={cn('h-4 w-4', loading && 'animate-spin')} />
        </button>
      </div>

      <div className="nf-scroll flex-1 overflow-auto bg-black/40 p-3">
        {error ? (
          <p className="text-sm text-danger">{error}</p>
        ) : loading && artifacts.length === 0 ? (
          <p className="text-sm text-white/40">Generating…</p>
        ) : !current ? (
          <Empty>No config artifacts yet. Click regenerate to build one.</Empty>
        ) : (
          <pre className="whitespace-pre-wrap font-mono text-[12.5px] leading-relaxed text-white/85">
            {current.content}
          </pre>
        )}
      </div>
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid h-full place-items-center p-6 text-center text-white/40">
      <div className="space-y-2">
        <FileCode2 className="mx-auto h-8 w-8" />
        <p className="text-xs">{children}</p>
      </div>
    </div>
  );
}
