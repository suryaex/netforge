/**
 * Per-node console hook. Opens /ws/console/{nodeId}, accumulates output lines
 * (capped to keep memory bounded), and exposes a `send` for keystrokes.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { consoleChannel } from '@/api/ws';
import type { ConnState } from '@/api/ws';
import type { ConsoleEvent } from '@/api/types';

const MAX_LINES = 2_000; // ring buffer cap — keeps long sessions light

export interface ConsoleSession {
  lines: string[];
  prompt: string;
  state: ConnState;
  send: (cmd: string) => void;
}

export function useConsoleChannel(nodeId: string | null): ConsoleSession {
  const [lines, setLines] = useState<string[]>([]);
  const [prompt, setPrompt] = useState<string>('');
  const [state, setState] = useState<ConnState>('connecting');
  const channelRef = useRef<ReturnType<typeof consoleChannel> | null>(null);

  useEffect(() => {
    if (!nodeId) return;
    setLines([]);
    const channel = consoleChannel(nodeId);
    channelRef.current = channel;

    const append = (chunk: string) =>
      setLines((prev) => {
        const next = prev.concat(chunk.split('\n'));
        return next.length > MAX_LINES ? next.slice(next.length - MAX_LINES) : next;
      });

    const offMsg = channel.onMessage((ev: ConsoleEvent) => {
      if (ev.type === 'output') {
        append(ev.data);
      } else if (ev.type === 'banner' || ev.type === 'error') {
        // Backend greets with a `banner` (carrying the device prompt) and
        // reports failures via `error`; both are plain text to display.
        append(ev.text);
      } else if (ev.type === 'prompt') {
        setPrompt(ev.prompt);
      } else if (ev.type === 'closed') {
        append(`\n[session closed${ev.reason ? `: ${ev.reason}` : ''}]`);
      }
    });
    const offState = channel.onState(setState);
    channel.connect();

    return () => {
      offMsg();
      offState();
      channel.close();
      channelRef.current = null;
    };
  }, [nodeId]);

  const send = useCallback((cmd: string) => {
    channelRef.current?.send({ type: 'input', data: cmd });
  }, []);

  return { lines, prompt, state, send };
}
