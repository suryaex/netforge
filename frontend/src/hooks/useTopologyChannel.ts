/**
 * Binds the /ws/topology channel to the topology store for the open project.
 * Mounts one channel for the app lifetime; feeds realtime events into the
 * store's reducer and exposes the connection state for status UI.
 */
import { useEffect, useState } from 'react';
import { topologyChannel } from '@/api/ws';
import type { ConnState } from '@/api/ws';
import { useTopologyStore } from '@/store/topologyStore';

export function useTopologyChannel(enabled: boolean, projectId?: string | null): ConnState {
  const applyEvent = useTopologyStore((s) => s.applyEvent);
  const [state, setState] = useState<ConnState>('connecting');

  useEffect(() => {
    if (!enabled || !projectId) return;
    const channel = topologyChannel(projectId);
    const offMsg = channel.onMessage(applyEvent);
    const offState = channel.onState(setState);
    channel.connect();
    return () => {
      offMsg();
      offState();
      channel.close();
    };
  }, [enabled, projectId, applyEvent]);

  return state;
}
