/**
 * MenuBar — top glass bar (macOS menu-bar analogue). Shows the app mark,
 * project name, realtime connection status, the simulation control bar, the
 * theme toggle, and a clock. Stays out of the canvas's way (height 36px).
 */
import { useEffect, useState } from 'react';
import { Moon, Sun, Wifi, WifiOff } from 'lucide-react';
import type { ConnState } from '@/api/ws';
import { useUiStore } from '@/store/uiStore';
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
  const [clock, setClock] = useState(() => new Date());

  useEffect(() => {
    const t = setInterval(() => setClock(new Date()), 30_000);
    return () => clearInterval(t);
  }, []);

  const online = conn === 'open';

  return (
    <header className="glass-strong fixed inset-x-0 top-0 z-[900] flex h-9 items-center gap-4 border-b border-white/10 px-3 text-[13px] text-white/85">
      <div className="flex items-center gap-2 font-semibold">
        <span className="grid h-5 w-5 place-items-center rounded bg-accent text-[11px] text-white">
          N
        </span>
        NetForge
      </div>

      <span className="text-white/40">/</span>
      <span className="truncate text-white/70">{projectName}</span>

      <div className="flex-1" />

      <SimulationBar />

      <div
        className={cn('flex items-center gap-1.5', online ? 'text-success' : 'text-warning')}
        title={`Realtime: ${conn}`}
      >
        {online ? <Wifi className="h-4 w-4" /> : <WifiOff className="h-4 w-4" />}
        <span className="hidden text-xs sm:inline">{conn}</span>
      </div>

      <UpdatesButton />

      <button
        onClick={toggleTheme}
        aria-label="Toggle theme"
        className="grid h-7 w-7 place-items-center rounded-md hover:bg-white/10"
      >
        {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
      </button>

      <time className="tabular-nums text-white/70">
        {clock.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
      </time>
    </header>
  );
}
