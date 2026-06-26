/**
 * MenuBar — top glass bar (macOS menu-bar analogue). Shows the app mark,
 * project name, realtime connection status, the simulation control bar, the
 * theme toggle, signed-in user avatar, and a clock.
 */
import { useEffect, useRef, useState } from 'react';
import { LogOut, Map, Moon, Network, Settings2, Sun, Wifi, WifiOff } from 'lucide-react';
import type { ConnState } from '@/api/ws';
import { useUiStore } from '@/store/uiStore';
import { useAuthStore } from '@/store/authStore';
import { useWindowStore } from '@/store/windowStore';
import { SimulationBar } from '@/components/SimulationBar';
import { UpdatesButton } from '@/components/shell/UpdatesButton';
import { cn } from '@/lib/cn';

interface MenuBarProps {
  projectName: string;
  conn: ConnState;
}

export function MenuBar({ projectName, conn }: MenuBarProps) {
  const theme = useUiStore((s) => s.theme);
  const toggleTheme = useUiStore((s) => s.toggleTheme);
  const viewMode = useUiStore((s) => s.viewMode);
  const setViewMode = useUiStore((s) => s.setViewMode);
  const username = useAuthStore((s) => s.username);
  const logout = useAuthStore((s) => s.logout);
  const toggleApp = useWindowStore((s) => s.toggleApp);
  const [clock, setClock] = useState(() => new Date());
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const userMenuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const t = setInterval(() => setClock(new Date()), 30_000);
    return () => clearInterval(t);
  }, []);

  // Close user menu on outside click.
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (userMenuRef.current && !userMenuRef.current.contains(e.target as Node)) {
        setUserMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const online = conn === 'open';

  return (
    <header className="glass-strong fixed inset-x-0 top-0 z-[900] flex h-9 items-center gap-3 border-b border-white/10 px-3 text-[13px] text-white/85">
      {/* Brand */}
      <div className="flex items-center gap-2 font-semibold">
        <span className="grid h-5 w-5 shrink-0 place-items-center rounded bg-accent text-[11px] font-bold text-white">
          N
        </span>
        <span className="hidden sm:inline">NetForge</span>
      </div>

      <span className="text-white/30">/</span>
      <span className="max-w-[140px] truncate text-white/65 sm:max-w-none">{projectName}</span>

      <div className="flex-1" />

      {/* Simulation controls (center) */}
      <SimulationBar />

      <div className="flex-1" />

      {/* View mode toggle */}
      <div className="flex items-center rounded-md border border-white/10 bg-white/5 p-0.5">
        <button
          onClick={() => setViewMode('topology')}
          aria-label="Topology view"
          title="Topology view"
          className={cn(
            'flex items-center gap-1.5 rounded px-2 py-1 text-xs transition-colors',
            viewMode === 'topology'
              ? 'bg-accent text-white'
              : 'text-white/50 hover:text-white/80',
          )}
        >
          <Network className="h-3.5 w-3.5" />
          <span className="hidden sm:inline">Topology</span>
        </button>
        <button
          onClick={() => setViewMode('map')}
          aria-label="Map view"
          title="Map view"
          className={cn(
            'flex items-center gap-1.5 rounded px-2 py-1 text-xs transition-colors',
            viewMode === 'map'
              ? 'bg-accent text-white'
              : 'text-white/50 hover:text-white/80',
          )}
        >
          <Map className="h-3.5 w-3.5" />
          <span className="hidden sm:inline">Map</span>
        </button>
      </div>

      {/* Right-side controls */}
      <div className="flex items-center gap-1.5">
        {/* Connection status */}
        <div
          className={cn(
            'flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs',
            online
              ? 'text-success'
              : 'text-warning',
          )}
          title={`Realtime channel: ${conn}`}
        >
          {online ? <Wifi className="h-3.5 w-3.5" /> : <WifiOff className="h-3.5 w-3.5" />}
          <span className="hidden lg:inline">{conn}</span>
        </div>

        <UpdatesButton />

        {/* Theme toggle */}
        <button
          onClick={toggleTheme}
          aria-label="Toggle theme"
          className="grid h-7 w-7 place-items-center rounded-md text-white/60 hover:bg-white/10 hover:text-white"
        >
          {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </button>

        {/* Settings shortcut */}
        <button
          onClick={() => toggleApp('settings', 'Settings')}
          aria-label="Open settings"
          className="grid h-7 w-7 place-items-center rounded-md text-white/60 hover:bg-white/10 hover:text-white"
        >
          <Settings2 className="h-4 w-4" />
        </button>

        {/* Clock */}
        <time className="tabular-nums text-white/50">
          {clock.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
        </time>

        {/* User avatar / menu */}
        <div className="relative" ref={userMenuRef}>
          <button
            onClick={() => setUserMenuOpen((v) => !v)}
            aria-label="User menu"
            className="grid h-7 w-7 place-items-center rounded-full bg-accent/25 text-xs font-semibold text-accent hover:bg-accent/40 transition-colors"
          >
            {username?.[0]?.toUpperCase() ?? '?'}
          </button>

          {userMenuOpen && (
            <div className="glass-strong absolute right-0 top-9 z-[1000] min-w-[160px] overflow-hidden rounded-lg border border-white/15 shadow-glass-lg animate-fade-in">
              <div className="border-b border-white/10 px-3 py-2">
                <p className="text-xs font-medium text-white/80">{username}</p>
                <p className="text-[10px] text-white/40">Local account</p>
              </div>
              <button
                onClick={() => { setUserMenuOpen(false); toggleApp('settings', 'Settings'); }}
                className="flex w-full items-center gap-2 px-3 py-2 text-xs text-white/70 hover:bg-white/8 hover:text-white"
              >
                <Settings2 className="h-3.5 w-3.5" /> Settings
              </button>
              <button
                onClick={logout}
                className="flex w-full items-center gap-2 px-3 py-2 text-xs text-danger/80 hover:bg-danger/10 hover:text-danger"
              >
                <LogOut className="h-3.5 w-3.5" /> Sign out
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
