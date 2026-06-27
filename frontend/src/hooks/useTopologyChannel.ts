/**
 * Binds the /ws/topology channel to the topology store for the open project.
 * Mounts one channel for the app lifetime; feeds realtime events into the
 * store's reducer and exposes the connection state for status UI.
 */
import { useEffect, useState } from 'react';
import { topologyChannel } from '@/api/ws';
import type { ConnState } from '@/api/ws';
import { useTopologyStore } from '@/store/topologyStore';
import { useUiStore } from '@/store/uiStore';

export function useTopologyChannel(enabled: boolean, projectId?: string | null): ConnState {
  const applyEvent = useTopologyStore((s) => s.applyEvent);
  const applySimTick = useUiStore((s) => s.applySimTick);
  const [state, setState] = useState<ConnState>('connecting');

  useEffect(() => {
    if (!enabled || !projectId) return;
    const channel = topologyChannel(projectId);
    // sim.tick carries live engine telemetry/state → UI store; everything else
    // is graph topology → topology store. Routing both keeps the transport bar
    // authoritative without the topology reducer needing to know about the sim.
    const offMsg = channel.onMessage((ev) => {
      if (ev.type === 'sim.tick') {
        applySimTick(ev.t, ev.metrics, ev.state);
        return;
      }
      applyEvent(ev);
    });
    const offState = channel.onState(setState);
    channel.connect();
    return () => {
      offMsg();
      offState();
      channel.close();
    };
  }, [enabled, projectId, applyEvent, applySimTick]);

  return state;
}
