/**
 * Map store — state for the satellite map view (UISP Design Center style).
 * Tracks devices placed on the real map (lat/lng), links between them,
 * the active tool, and the selected device.
 *
 * Signal simulation uses Free Space Path Loss (FSPL).
 */
import { create } from 'zustand';

export type MapTool = 'select' | 'ap' | 'cpe' | 'tower' | 'measure';
export type MapDeviceKind = 'ap' | 'cpe' | 'tower';

export interface MapDevice {
  id: string;
  name: string;
  kind: MapDeviceKind;
  lat: number;
  lng: number;
  txPower: number;    // dBm (e.g. 20)
  frequency: number;  // GHz (e.g. 5.8)
  range: number;      // meters — max coverage radius for the ring
  ip: string;
}

export interface MapLink {
  id: string;
  fromId: string;
  toId: string;
  distance: number; // meters
  rssi: number;     // dBm
}

/** FSPL-based RSSI estimate. */
export function calcRssi(txPower: number, distanceM: number, freqGhz: number): number {
  if (distanceM < 1) return txPower;
  const fHz = freqGhz * 1e9;
  const fspl = 20 * Math.log10(distanceM) + 20 * Math.log10(fHz) - 147.55;
  return Math.round((txPower - fspl) * 10) / 10;
}

/** Haversine distance in metres between two lat/lng points. */
export function haversineM(lat1: number, lng1: number, lat2: number, lng2: number): number {
  const R = 6371000;
  const dLat = ((lat2 - lat1) * Math.PI) / 180;
  const dLng = ((lng2 - lng1) * Math.PI) / 180;
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos((lat1 * Math.PI) / 180) *
      Math.cos((lat2 * Math.PI) / 180) *
      Math.sin(dLng / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

/** Link quality from RSSI value. */
export function rssiColor(rssi: number): string {
  if (rssi >= -55) return '#34C759'; // strong
  if (rssi >= -70) return '#A3E635'; // good
  if (rssi >= -80) return '#FFCC00'; // fair
  return '#FF453A';                   // weak
}

interface MapState {
  devices: Map<string, MapDevice>;
  links: Map<string, MapLink>;
  selectedDeviceId: string | null;
  tool: MapTool;
  showOnboarding: boolean;
  mapCenter: [number, number];
  mapZoom: number;

  // selectors
  deviceList: () => MapDevice[];
  linkList: () => MapLink[];
  selectedDevice: () => MapDevice | null;

  // mutations
  addDevice: (d: Omit<MapDevice, 'id'>) => string;
  updateDevice: (id: string, patch: Partial<MapDevice>) => void;
  removeDevice: (id: string) => void;
  selectDevice: (id: string | null) => void;
  setTool: (tool: MapTool) => void;
  dismissOnboarding: () => void;
  setMapView: (center: [number, number], zoom: number) => void;

  /** Rebuild all links after a device move or add. */
  rebuildLinks: () => void;
}

let seq = 0;
const nextId = (prefix: string) => `${prefix}-${++seq}`;

export const useMapStore = create<MapState>((set, get) => ({
  devices: new Map(),
  links: new Map(),
  selectedDeviceId: null,
  tool: 'select',
  showOnboarding: true,
  mapCenter: [-6.2, 106.8], // Jakarta default
  mapZoom: 13,

  deviceList: () => Array.from(get().devices.values()),
  linkList: () => Array.from(get().links.values()),
  selectedDevice: () => {
    const id = get().selectedDeviceId;
    return id ? (get().devices.get(id) ?? null) : null;
  },

  addDevice: (d) => {
    const id = nextId(d.kind);
    set((s) => {
      const devices = new Map(s.devices);
      devices.set(id, { ...d, id });
      return { devices };
    });
    get().rebuildLinks();
    return id;
  },

  updateDevice: (id, patch) => {
    set((s) => {
      const dev = s.devices.get(id);
      if (!dev) return {};
      const devices = new Map(s.devices);
      devices.set(id, { ...dev, ...patch });
      return { devices };
    });
    get().rebuildLinks();
  },

  removeDevice: (id) => {
    set((s) => {
      const devices = new Map(s.devices);
      devices.delete(id);
      const links = new Map(s.links);
      for (const [lid, l] of links) {
        if (l.fromId === id || l.toId === id) links.delete(lid);
      }
      return {
        devices,
        links,
        selectedDeviceId: s.selectedDeviceId === id ? null : s.selectedDeviceId,
      };
    });
  },

  selectDevice: (id) => set({ selectedDeviceId: id }),
  setTool: (tool) => set({ tool }),
  dismissOnboarding: () => set({ showOnboarding: false }),
  setMapView: (center, zoom) => set({ mapCenter: center, mapZoom: zoom }),

  rebuildLinks: () => {
    const { devices } = get();
    const list = Array.from(devices.values());
    const links = new Map<string, MapLink>();

    // Find nearest AP for every CPE; AP-Tower also get links.
    const aps = list.filter((d) => d.kind === 'ap' || d.kind === 'tower');

    for (const dev of list) {
      if (dev.kind === 'ap') continue; // AP links built from CPE side

      let bestAp: MapDevice | null = null;
      let bestDist = Infinity;

      for (const ap of aps) {
        if (ap.id === dev.id) continue;
        const dist = haversineM(dev.lat, dev.lng, ap.lat, ap.lng);
        if (dist < bestDist && dist <= ap.range) {
          bestDist = dist;
          bestAp = ap;
        }
      }

      if (bestAp) {
        const linkId = [bestAp.id, dev.id].sort().join('--');
        if (!links.has(linkId)) {
          const rssi = calcRssi(bestAp.txPower, bestDist, bestAp.frequency);
          links.set(linkId, {
            id: linkId,
            fromId: bestAp.id,
            toId: dev.id,
            distance: Math.round(bestDist),
            rssi,
          });
        }
      }
    }

    set({ links });
  },
}));
