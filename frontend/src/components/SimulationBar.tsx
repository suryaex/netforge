/**
 * SimulationBar — transport controls for the discrete-event engine.
 * Play / pause / step / stop + speed selector. Calls the REST sim endpoints
 * and reflects optimistic state; the authoritative state arrives via sim.tick
 * events on /ws/topology.
 */
import { Pause, Play, Square, StepForward } from 'lucide-react';
import { simApi } from '@/api/client';
import { useUiStore } from '@/store/uiStore';
import { cn } from '@/lib/cn';

const SPEEDS = [0.5, 1, 2, 4, 8];

export function SimulationBar() {
  const { simState, simSpeed, setSimState, setSimSpeed, projectId } = useUiStore();

  const guarded = (nextState: typeof simState, fn: () => Promise<unknown>) => {
    if (!projectId) return;
    setSimState(nextState);
    void fn().catch(() => setSimState('idle'));
  };

  const onPlay = () =>
    // Resume a paused/stepped run; only a fresh `idle` engine is (re)started.
    guarded('running', () =>
      simState === 'idle'
        ? simApi.start({ project_id: projectId!, realtime: true })
        : simApi.resume(projectId!),
    );
  const onPause = () =>
    guarded('paused', () => simApi.pause(projectId!));
  // After a single step the engine is paused — reflect that so Play resumes.
  const onStep = () =>
    guarded('paused', () => simApi.step(projectId!));
  const onStop = () =>
    guarded('idle', () => simApi.stop(projectId!));

  const running = simState === 'running';

  return (
    <div className="flex items-center gap-1 rounded-md border border-white/10 bg-white/5 px-1 py-0.5">
      <CtrlButton label={running ? 'Pause' : 'Play'} onClick={running ? onPause : onPlay} active={running}>
        {running ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
      </CtrlButton>
      <CtrlButton label="Step" onClick={onStep}>
        <StepForward className="h-4 w-4" />
      </CtrlButton>
      <CtrlButton label="Stop" onClick={onStop}>
        <Square className="h-4 w-4" />
      </CtrlButton>

      <select
        aria-label="Simulation speed"
        value={simSpeed}
        onChange={(e) => setSimSpeed(Number(e.target.value))}
        className="ml-1 rounded bg-transparent px-1 text-xs text-white/80 outline-none"
      >
        {SPEEDS.map((s) => (
          <option key={s} value={s} className="bg-[#141A2E]">
            {s}×
          </option>
        ))}
      </select>
    </div>
  );
}

function CtrlButton({
  label,
  onClick,
  active,
  children,
}: {
  label: string;
  onClick: () => void;
  active?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      aria-label={label}
      title={label}
      className={cn(
        'grid h-7 w-7 place-items-center rounded transition-colors',
        active ? 'bg-accent text-white' : 'text-white/80 hover:bg-white/10',
      )}
    >
      {children}
    </button>
  );
}
