/**
 * UI store — global, app-wide UI state that isn't graph or window geometry:
 * theme mode, simulation state, and the currently-open project id.
 * Persists theme to localStorage; everything else is session state.
 */
import { create } from 'zustand';
import { applyTheme, type ThemeMode } from '@/theme/tokens';
import type { SimState } from '@/api/types';

const THEME_KEY = 'netforge.theme';

export type ViewMode = 'topology' | 'map';

function initialTheme(): ThemeMode {
  const saved = localStorage.getItem(THEME_KEY) as ThemeMode | null;
  if (saved === 'light' || saved === 'dark') return saved;
  return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}

interface UiState {
  theme: ThemeMode;
  simState: SimState;
  simSpeed: number;
  /** Latest engine virtual-clock time (seconds), from sim.tick telemetry. */
  simTime: number;
  /** Latest engine metrics (delivered/dropped/...), from sim.tick telemetry. */
  simMetrics: Record<string, number> | null;
  projectId: string | null;
  viewMode: ViewMode;

  setTheme: (mode: ThemeMode) => void;
  toggleTheme: () => void;
  setSimState: (s: SimState) => void;
  setSimSpeed: (n: number) => void;
  /** Apply authoritative telemetry from a /ws/topology sim.tick event. */
  applySimTick: (
    t: number,
    metrics?: Record<string, number>,
    state?: SimState | 'completed' | 'stopped' | 'error',
  ) => void;
  setProject: (id: string | null) => void;
  setViewMode: (mode: ViewMode) => void;
}

export const useUiStore = create<UiState>((set, get) => ({
  theme: initialTheme(),
  simState: 'idle',
  simSpeed: 1,
  simTime: 0,
  simMetrics: null,
  projectId: null,
  viewMode: 'topology',

  setTheme: (mode) => {
    applyTheme(mode);
    localStorage.setItem(THEME_KEY, mode);
    set({ theme: mode });
  },
  toggleTheme: () => get().setTheme(get().theme === 'dark' ? 'light' : 'dark'),
  setSimState: (simState) => set({ simState }),
  setSimSpeed: (simSpeed) => set({ simSpeed }),
  applySimTick: (t, metrics, state) =>
    set((s) => {
      // Terminal engine states snap the transport bar back to idle; running and
      // paused are authoritative and override the optimistic local state.
      let next = s.simState;
      if (state === 'completed' || state === 'stopped' || state === 'error') next = 'idle';
      else if (state === 'running' || state === 'paused') next = state;
      return { simTime: t, simMetrics: metrics ?? s.simMetrics, simState: next };
    }),
  setProject: (projectId) => set({ projectId }),
  setViewMode: (viewMode) => set({ viewMode }),
}));
