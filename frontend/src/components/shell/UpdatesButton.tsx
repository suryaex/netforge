/**
 * UpdatesButton — menu-bar control that checks GitHub for a newer NetForge
 * release and lets an operator apply it (pull + rebuild + restart) from the app.
 *
 * The mutating call is guarded by a shared secret (UPDATE_TOKEN on the backend);
 * the user is prompted for it before applying. After "apply" we poll status and
 * surface progress until the backend restarts.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { Download, Loader2, RefreshCw } from 'lucide-react';
import { updateApi, type UpdateCheck, type UpdateStatus } from '@/api/client';
import { cn } from '@/lib/cn';

export function UpdatesButton() {
  const [open, setOpen] = useState(false);
  const [info, setInfo] = useState<UpdateCheck | null>(null);
  const [status, setStatus] = useState<UpdateStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval>>();

  const check = useCallback(async () => {
    setBusy(true);
    try {
      setInfo(await updateApi.check());
    } catch {
      setInfo({
        current: '?',
        latest: null,
        update_available: false,
        checked_at: Date.now() / 1000,
        error: 'Could not reach the backend.',
      });
    } finally {
      setBusy(false);
    }
  }, []);

  // Check on first open, and once a day in the background.
  useEffect(() => {
    void check();
    const t = setInterval(() => void check(), 24 * 60 * 60 * 1000);
    return () => clearInterval(t);
  }, [check]);

  useEffect(() => () => clearInterval(pollRef.current), []);

  const apply = useCallback(async () => {
    const token = window.prompt('Enter the update token (UPDATE_TOKEN) to apply:');
    if (!token) return;
    setBusy(true);
    try {
      setStatus(await updateApi.apply(token));
      // Poll status until the backend goes away (restart) or reports done/error.
      clearInterval(pollRef.current);
      pollRef.current = setInterval(async () => {
        try {
          const s = await updateApi.status();
          setStatus(s);
          if (s.state === 'done' || s.state === 'error' || s.state === 'up-to-date') {
            clearInterval(pollRef.current);
            if (s.state === 'done') setTimeout(() => window.location.reload(), 2000);
          }
        } catch {
          // Backend unreachable === it's restarting. Reload shortly.
          setStatus({ state: 'restarting', message: 'App is restarting…' });
        }
      }, 3000);
    } catch (e) {
      setStatus({ state: 'error', message: (e as { message?: string })?.message ?? 'Apply failed.' });
    } finally {
      setBusy(false);
    }
  }, []);

  const available = info?.update_available;

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-label="Updates"
        title={available ? `Update available: ${info?.latest}` : 'Check for updates'}
        className={cn(
          'relative grid h-7 w-7 place-items-center rounded-md hover:bg-white/10',
          available && 'text-accent',
        )}
      >
        <Download className="h-4 w-4" />
        {available && (
          <span className="absolute right-1 top-1 h-1.5 w-1.5 rounded-full bg-accent" />
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-9 z-[1000] w-72 rounded-lg border border-white/10 bg-black/80 p-3 text-[13px] text-white/85 shadow-xl backdrop-blur">
          <div className="mb-2 flex items-center justify-between">
            <span className="font-semibold">Software update</span>
            <button
              onClick={() => void check()}
              className="grid h-6 w-6 place-items-center rounded hover:bg-white/10"
              title="Check again"
            >
              <RefreshCw className={cn('h-3.5 w-3.5', busy && 'animate-spin')} />
            </button>
          </div>

          <div className="space-y-1 text-white/70">
            <div>
              Current: <span className="tabular-nums text-white">{info?.current ?? '…'}</span>
            </div>
            <div>
              Latest:{' '}
              <span className="tabular-nums text-white">
                {info?.latest ?? (info?.error ? '—' : '…')}
              </span>
            </div>
          </div>

          {info?.error && <p className="mt-2 text-xs text-warning">{info.error}</p>}

          {available ? (
            <>
              {info?.notes && (
                <p className="mt-2 max-h-24 overflow-auto whitespace-pre-wrap text-xs text-white/60">
                  {info.notes}
                </p>
              )}
              <button
                onClick={() => void apply()}
                disabled={busy || !info?.can_apply}
                className="mt-3 flex w-full items-center justify-center gap-2 rounded-md bg-accent px-3 py-1.5 font-medium text-white disabled:opacity-50"
              >
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
                Update &amp; restart
              </button>
              {!info?.can_apply && (
                <p className="mt-1 text-[11px] text-white/40">
                  Applying from the app is disabled (set UPDATE_TOKEN on the backend).
                </p>
              )}
            </>
          ) : (
            !info?.error && <p className="mt-2 text-xs text-success">You&apos;re up to date.</p>
          )}

          {status && (
            <p className="mt-2 border-t border-white/10 pt-2 text-xs text-white/70">
              <span className="font-medium capitalize">{status.state}</span>
              {status.message ? ` — ${status.message}` : ''}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
