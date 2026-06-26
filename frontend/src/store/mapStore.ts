/**
 * Map store — state for the satellite map view (UISP Design Center style).
 * Tracks devices placed on the real map (lat/lng), links between them,
 * the active tool, and the selected device.
 *
 * Signal simulation uses:
 *  - Free Space Path Loss (FSPL)
 *  - ITU-R P.838 rain attenuation
 *  - Line-of-sight / Fresnel zone check (async via Open Elevation API)
 */
import { create } from 'zustand';
import type { LosStatus } from '@/services/signalSim';
import type { MapTileKey } from '@/config/mapTiles';
import { DEFAULT_TILE } from '@/config/mapTiles';

export type MapTool = 'select' | 'ap' | 'cpe' | 'tower' | 'measure';
export type MapDeviceKind = 'ap' | 'cpe' | 'tower';

export interface MapDevice {
  id: string;
  name: string;
  kind: MapDeviceKind;
  lat: number;
  lng: number;
  txPower: number;     // dBm (e.g. 20)
  frequency: number;   // GHz (e.g. 5.8)
  range: number;       // meters — max coverage radius for the ring
  antennaHeight: number; // meters AGL (above ground level)
  ip: string;
}

export interface MapLink {
  id: string;
  fromId: string;
  toId: string;
  distance: number;    // meters
  rssi: number;        // dBm (FSPL only, instant)
  los: LosStatus;      // updated async
  rainDb: number;      // dB attenuation from rain
  obstructionDb: number; // dB attenuation from terrain
  fresnelM: number;    // first Fresnel zone radius at midpoint (metres)
}

/** FSPL-based RSSI estimate (no terrain/rain). */
export function calcRssi(txPower: number, distanceM: number, freqGhz: number): number {
  if (distanceM < 1) return txPower;
  const fHz = freqGhz * 1e9;
  const fspl = 20 * Math.log10(distanceM) + 20 * Math.log10(fHz) - 147.55;
  return Math.round((txPower - fspl) * 10) / 10;
}

/** Haversine distance in metres between two lat/lng points. */
export function haversineM(lat1: number, lng1: number, lat2: number, lng2: number): number {
  const R = 6_371_000;
  const dLat = ((lat2 - lat1) * Math.PI) / 180;
  const dLng = ((lng2 - lng1) * Math.PI) / 180;
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos((lat1 * Math.PI) / 180) *
      Math.cos((lat2 * Math.PI) / 180) *
      Math.sin(dLng / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

/** First Fresnel zone radius (m) at midpoint of a link. */
function fresnelAtMid(distanceM: number, freqGhz: number): number {
  const c = 3e8;
  const lambda = c / (freqGhz * 1e9);
  const d = distanceM / 2;
  return Math.sqrt((lambda * d * d) / (d + d));
}

/** Link quality color from RSSI. */
export function rssiColor(rssi: number): string {
  if (rssi >= -55) return '#34C759'; // strong
  if (rssi >= -70) return '#A3E635'; // good
  if (rssi >= -80) return '#FFCC00'; // fair
  return '#FF453A';                   // weak
}

/** Link color accounting for LOS status. */
export function linkColor(link: MapLink): string {
  if (link.los === 'blocked') return '#FF453A';
  if (link.los === 'partial') return '#FFCC00';
  return rssiColor(link.rssi - link.rainDb - link.obstructionDb);
}

/** Rain rate description. */
export function rainRateLabel(mmhr: number): string {
  if (mmhr === 0) return 'Clear';
  if (mmhr <= 2.5) return 'Drizzle';
  if (mmhr <= 10) return 'Light Rain';
  if (mmhr <= 25) return 'Moderate Rain';
  if (mmhr <= 50) return 'Heavy Rain';
  return 'Violent Rain';
}

interface MapState {
  devices: Map<string, MapDevice>;
  links: Map<string, MapLink>;
  selectedDeviceId: string | null;
  tool: MapTool;
  showOnboarding: boolean;
  mapCenter: [number, number];
  mapZoom: number;
  mapLayer: MapTileKey;       // active basemap (satellite / street / hybrid / …)
  deviceLibraryOpen: boolean; // device-type library modal visibility
  rainRate: number;     // mm/hr (0 = clear sky)
  checkingLos: boolean; // async LOS check in progress

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
  setMapLayer: (layer: MapTileKey) => void;
  openDeviceLibrary: () => void;
  closeDeviceLibrary: () => void;
  setRainRate: (rate: number) => void;
  setCheckingLos: (v: boolean) => void;
  updateLinkLos: (linkId: string, los: LosStatus, obstructionDb: number) => void;

  /** Rebuild all links (fast, synchronous FSPL only). */
  rebuildLinks: () => void;
  /** Trigger async LOS check for all current links. */
  triggerLosCheck: () => Promise<void>;
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
  mapLayer: DEFAULT_TILE,
  deviceLibraryOpen: false,
  rainRate: 0,
  checkingLos: false,

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
    // Trigger async LOS check after a short delay to batch updates.
    setTimeout(() => void get().triggerLosCheck(), 300);
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
    setTimeout(() => void get().triggerLosCheck(), 300);
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
  setMapLayer: (mapLayer) => set({ mapLayer }),
  openDeviceLibrary: () => set({ deviceLibraryOpen: true }),
  closeDeviceLibrary: () => set({ deviceLibraryOpen: false }),
  setRainRate: (rainRate) => {
    set({ rainRate });
    get().rebuildLinks();
  },
  setCheckingLos: (checkingLos) => set({ checkingLos }),

  updateLinkLos: (linkId, los, obstructionDb) =>
    set((s) => {
      const link = s.links.get(linkId);
      if (!link) return {};
      const links = new Map(s.links);
      const from = s.devices.get(link.fromId);
      const rainDb = from
        ? (() => {
            // re-import dynamically to avoid circular dep at top level
            const { rainRate } = s;
            if (rainRate <= 0) return 0;
            const k = from.frequency <= 3 ? 0.0001071 : from.frequency <= 6 ? 0.0091 : 0.3171;
            const alpha = from.frequency <= 3 ? 1.6009 : from.frequency <= 6 ? 1.217 : 0.8545;
            return k * Math.pow(rainRate, alpha) * (link.distance / 1000);
          })()
        : 0;

      const newRssi = from
        ? calcRssi(from.txPower, link.distance, from.frequency) - rainDb - obstructionDb
        : link.rssi;

      links.set(linkId, { ...link, los, obstructionDb, rainDb, rssi: newRssi });
      return { links };
    }),

  rebuildLinks: () => {
    const { devices, rainRate } = get();
    const list = Array.from(devices.values());
    const links = new Map<string, MapLink>();
    const aps = list.filter((d) => d.kind === 'ap' || d.kind === 'tower');

    for (const dev of list) {
      if (dev.kind === 'ap') continue;

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
          const existingLink = get().links.get(linkId);
          const rssi = calcRssi(bestAp.txPower, bestDist, bestAp.frequency);

          // Rain attenuation
          const k = bestAp.frequency <= 3 ? 0.0001071 : bestAp.frequency <= 6 ? 0.0091 : 0.3171;
          const alpha = bestAp.frequency <= 3 ? 1.6009 : bestAp.frequency <= 6 ? 1.217 : 0.8545;
          const rainDb = rainRate > 0 ? k * Math.pow(rainRate, alpha) * (bestDist / 1000) : 0;

          links.set(linkId, {
            id: linkId,
            fromId: bestAp.id,
            toId: dev.id,
            distance: Math.round(bestDist),
            rssi: Math.round((rssi - rainDb) * 10) / 10,
            los: existingLink?.los ?? 'unknown',
            rainDb: Math.round(rainDb * 10) / 10,
            obstructionDb: existingLink?.obstructionDb ?? 0,
            fresnelM: Math.round(fresnelAtMid(bestDist, bestAp.frequency) * 10) / 10,
          });
        }
      }
    }

    set({ links });
  },

  triggerLosCheck: async () => {
    const { devices, links, checkingLos } = get();
    if (checkingLos) return; // debounce

    const linkList = Array.from(links.values());
    if (linkList.length === 0) return;

    set({ checkingLos: true });

    try {
      // Dynamic import to avoid loading the heavy elevation module until needed.
      const { computeSignal } = await import('@/services/signalSim');
      const { rainRate } = get();

      await Promise.all(
        linkList.map(async (link) => {
          const from = devices.get(link.fromId);
          const to = devices.get(link.toId);
          if (!from || !to) return;

          try {
            const result = await computeSignal({
              txPower: from.txPower,
              distanceM: link.distance,
              freqGhz: from.frequency,
              rainRateMmHr: rainRate,
              lat1: from.lat, lng1: from.lng, altAgl1: from.antennaHeight,
              lat2: to.lat, lng2: to.lng, altAgl2: to.antennaHeight,
            });

            get().updateLinkLos(link.id, result.los, result.obstructionDb);
          } catch {
            // Per-link error: mark as unknown, don't crash.
            get().updateLinkLos(link.id, 'unknown', 0);
          }
        }),
      );
    } finally {
      set({ checkingLos: false });
    }
  },
}));
