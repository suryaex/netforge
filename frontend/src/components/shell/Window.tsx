/**
 * Window — the glass window chrome for the desktop shell.
 * Provides macOS-style traffic-light controls, a draggable titlebar, focus
 * raising, and minimize/maximize. Pointer-based dragging uses a ref + rAF so
 * dragging large windows (with a heavy canvas inside) stays at 60fps.
 *
 * Accessibility: titlebar is a focusable region with role="dialog", controls
 * are real <button>s with aria-labels, Escape closes the focused window.
 */
import { useCallback, useEffect, useRef, type ReactNode } from 'react';
import { Minus, Square, X } from 'lucide-react';
import { useWindowStore, type WindowInstance } from '@/store/windowStore';
import { cn } from '@/lib/cn';

interface WindowProps {
  win: WindowInstance;
  children: ReactNode;
  /** Optional toolbar rendered to the right of the title. */
  toolbar?: ReactNode;
}

export function Window({ win, children, toolbar }: WindowProps) {
  const { focus, close, move, toggleMinimize, toggleMaximize, focusedId } = useWindowStore();
  const dragRef = useRef<{ ox: number; oy: number } | null>(null);
  const rafRef = useRef<number | null>(null);
  const isFocused = focusedId === win.id;

  const onTitlePointerDown = useCallback(
    (e: React.PointerEvent) => {
      if (win.maximized) return;
      focus(win.id);
      (e.target as HTMLElement).setPointerCapture(e.pointerId);
      dragRef.current = { ox: e.clientX - win.rect.x, oy: e.clientY - win.rect.y };
    },
    [focus, win.id, win.maximized, win.rect.x, win.rect.y],
  );

  const onTitlePointerMove = useCallback(
    (e: React.PointerEvent) => {
      if (!dragRef.current) return;
      const { ox, oy } = dragRef.current;
      const x = e.clientX - ox;
      const y = Math.max(36, e.clientY - oy); // never hide under the menu bar
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      rafRef.current = requestAnimationFrame(() => move(win.id, x, y));
    },
    [move, win.id],
  );

  const endDrag = useCallback(() => {
    dragRef.current = null;
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isFocused) close(win.id);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [close, isFocused, win.id]);

  if (win.minimized) return null;

  const MIN_W = 200;
  const MIN_H = 140;

  const geometry: React.CSSProperties = win.maximized
    ? { left: 8, top: 40, width: 'calc(100vw - 16px)', height: 'calc(100vh - 120px)' }
    : {
        left: win.rect.x,
        top: win.rect.y,
        width: win.rect.w,
        height: win.rect.h,
        minWidth: MIN_W,
        minHeight: MIN_H,
      };

  return (
    <section
      role="dialog"
      aria-label={win.title}
      aria-modal={false}
      onPointerDown={() => focus(win.id)}
      style={{ ...geometry, zIndex: win.z }}
      className={cn(
        'absolute flex flex-col overflow-hidden rounded-lg border animate-scale-in',
        'glass-strong shadow-window',
        isFocused ? 'border-white/20' : 'border-white/10 opacity-95',
      )}
    >
      {/* Titlebar */}
      <header
        onPointerDown={onTitlePointerDown}
        onPointerMove={onTitlePointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        onDoubleClick={() => toggleMaximize(win.id)}
        className="flex h-9 shrink-0 cursor-default select-none items-center gap-3 border-b border-white/10 px-3"
      >
        <div className="group flex items-center gap-2">
          <button
            aria-label="Close window"
            onClick={() => close(win.id)}
            className="traffic bg-[#FF5F57] hover:opacity-80"
          >
            <X className="m-auto h-2 w-2 text-black/50 opacity-0 group-hover:opacity-100" />
          </button>
          <button
            aria-label="Minimize window"
            onClick={() => toggleMinimize(win.id)}
            className="traffic bg-[#FEBC2E] hover:opacity-80"
          >
            <Minus className="m-auto h-2 w-2 text-black/50 opacity-0 group-hover:opacity-100" />
          </button>
          <button
            aria-label="Maximize window"
            onClick={() => toggleMaximize(win.id)}
            className="traffic bg-[#28C840] hover:opacity-80"
          >
            <Square className="m-auto h-1.5 w-1.5 text-black/50 opacity-0 group-hover:opacity-100" />
          </button>
        </div>

        <span className="flex-1 truncate text-center text-[13px] font-medium text-ink/80 dark:text-white/80">
          {win.title}
        </span>

        <div className="flex items-center gap-1">{toolbar}</div>
      </header>

      {/* Body */}
      <div className="nf-scroll min-h-0 flex-1 overflow-auto">{children}</div>
    </section>
  );
}
