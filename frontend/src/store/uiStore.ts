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
  projectId: string | null;
  viewMode: ViewMode;

  setTheme: (mode: ThemeMode) => void;
  toggleTheme: () => void;
  setSimState: (s: SimState) => void;
  setSimSpeed: (n: number) => void;
  setProject: (id: string | null) => void;
  setViewMode: (mode: ViewMode) => void;
}

export const useUiStore = create<UiState>((set, get) => ({
  theme: initialTheme(),
  simState: 'idle',
  simSpeed: 1,
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
  setProject: (projectId) => set({ projectId }),
  setViewMode: (viewMode) => set({ viewMode }),
}));
