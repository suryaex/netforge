/**
 * MapView — satellite map-based network design view (UISP Design Center style).
 *
 * Features:
 *  - Esri World Imagery satellite tiles (free, no key)
 *  - CARTO dark label overlay
 *  - Click-to-place devices (AP, CPE, Tower) with the active tool
 *  - Signal coverage rings (strong→weak gradient via concentric circles)
 *  - Links drawn as polylines colored by RSSI + LOS quality
 *  - Dashed link = blocked LOS, semi-dashed = partial Fresnel obstruction
 *  - Tooltip on hover: RSSI, distance, LOS status, rain attenuation
 *  - Left toolbar (MapToolbar) + right properties panel (MapDevicePanel)
 *  - Welcome onboarding modal (MapOnboardingModal)
 *  - Distance measure tool
 *  - Weather overlay (rain rate indicator)
 *  - LOS checking spinner
 */
import 'leaflet/dist/leaflet.css';
import { useState, useEffect, useRef } from 'react';
import {
  MapContainer,
  TileLayer,
  Circle,
  Polyline,
  CircleMarker,
  Popup,
  Tooltip,
  useMapEvents,
  useMap,
  ZoomControl,
} from 'react-leaflet';
import type { LeafletMouseEvent } from 'leaflet';
import L from 'leaflet';
import {
  useMapStore,
  linkColor,
  haversineM,
  rainRateLabel,
  type MapDevice,
  type MapLink,
  type MapDeviceKind,
} from '@/store/mapStore';
import {
  fetchOsmTowers,
  towerLabel,
  towerKind,
  type OsmTower,
} from '@/services/osmService';
import { MapToolbar } from './MapToolbar';
import { MapDevicePanel } from './MapDevicePanel';
import { MapOnboardingModal } from './MapOnboardingModal';

// Prevent default marker icon 404 errors in Vite. We use CircleMarker, not Marker.
delete (L.Icon.Default.prototype as unknown as Record<string, unknown>)['_getIconUrl'];
L.Icon.Default.mergeOptions({ iconUrl: '', iconRetinaUrl: '', shadowUrl: '' });

/* -------------------------------------------------------------------------- */
/* Signal coverage color stops (strong → weak, outermost ring = weakest)      */
/* -------------------------------------------------------------------------- */
const COVERAGE_RINGS = [
  { pct: 0.25, color: '#34C759', opacity: 0.20 }, // strong core
  { pct: 0.5,  color: '#A3E635', opacity: 0.13 },
  { pct: 0.75, color: '#FFCC00', opacity: 0.09 },
  { pct: 1.0,  color: '#FF453A', opacity: 0.05 }, // weak edge
];

/* -------------------------------------------------------------------------- */
/* Device kind display                                                         */
/* -------------------------------------------------------------------------- */
const KIND_COLOR: Record<MapDeviceKind, string> = {
  ap: '#5856D6',
  cpe: '#007AFF',
  tower: '#FF9F0A',
};

const KIND_LABEL: Record<MapDeviceKind, string> = {
  ap: 'AP',
  cpe: 'CPE',
  tower: 'TWR',
};

/* -------------------------------------------------------------------------- */
/* LOS dash pattern                                                            */
/* -------------------------------------------------------------------------- */
function losDashArray(los: MapLink['los']): string {
  if (los === 'blocked') return '8 6';
  if (los === 'partial') return '14 4';
  return '0'; // clear = solid
}

/* -------------------------------------------------------------------------- */
/* OSM tower kind styling                                                       */
/* -------------------------------------------------------------------------- */
const OSM_KIND_COLOR: Record<string, string> = {
  bts:       '#FF6B00', // orange — mobile BTS
  mast:      '#E040FB', // purple — generic mast
  microwave: '#00E5FF', // cyan — microwave link
  broadcast: '#FFD600', // yellow — broadcast tower
};

const OSM_KIND_LABEL: Record<string, string> = {
  bts:       'BTS',
  mast:      'MAST',
  microwave: 'MW',
  broadcast: 'TX',
};

/**
 * OsmTowerLayer — fetches existing telecom towers from OpenStreetMap and
 * renders them as small diamond-shaped markers so they are visually distinct
 * from user-placed devices.
 *
 * Fetches are triggered whenever the map viewport changes (moveend) and the
 * zoom level is >= 12 (avoids fetching too large an area).
 */
function OsmTowerLayer() {
  const map = useMap();
  const [towers, setTowers] = useState<OsmTower[]>([]);
  const [loading, setLoading] = useState(false);
  const abortRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const load = () => {
      if (map.getZoom() < 12) {
        setTowers([]);
        return;
      }
      if (abortRef.current) clearTimeout(abortRef.current);
      // Debounce 600 ms to avoid hammering Overpass during rapid pan
      abortRef.current = setTimeout(() => {
        const bounds = map.getBounds();
        setLoading(true);
        fetchOsmTowers(
          bounds.getSouth(),
          bounds.getWest(),
          bounds.getNorth(),
          bounds.getEast(),
        ).then((result) => {
          setTowers(result);
          setLoading(false);
        });
      }, 600);
    };

    map.on('moveend', load);
    map.on('zoomend', load);
    load(); // initial load

    return () => {
      map.off('moveend', load);
      map.off('zoomend', load);
      if (abortRef.current) clearTimeout(abortRef.current);
    };
  }, [map]);

  return (
    <>
      {towers.map((tower) => {
        const kind = towerKind(tower);
        const color = OSM_KIND_COLOR[kind] ?? '#FF6B00';
        const label = OSM_KIND_LABEL[kind] ?? 'BTS';
        const name = towerLabel(tower);

        return (
          <CircleMarker
            key={tower.id}
            center={[tower.lat, tower.lng]}
            radius={6}
            pathOptions={{
              color,
              fillColor: color,
              fillOpacity: 0.25,
              weight: 2,
              opacity: 0.85,
            }}
          >
            <Tooltip
              permanent={false}
              direction="top"
              offset={[0, -8]}
              className="nf-map-label"
            >
              <span style={{ color, fontWeight: 600, fontSize: 10 }}>
                [{label}] {name}
              </span>
            </Tooltip>
            <Popup>
              <div className="min-w-[160px] space-y-1 p-1">
                <p className="text-sm font-bold" style={{ color }}>
                  {name}
                </p>
                <p className="text-xs text-gray-500">
                  OSM ID: {tower.id} · Type: {label}
                </p>
                {tower.tags.operator && (
                  <p className="text-xs text-gray-600">Operator: {tower.tags.operator}</p>
                )}
                {tower.tags.height && (
                  <p className="text-xs text-gray-600">Height: {tower.tags.height} m</p>
                )}
                <p className="font-mono text-[10px] text-gray-400">
                  {tower.lat.toFixed(6)}, {tower.lng.toFixed(6)}
                </p>
                <p className="text-[9px] text-gray-400 italic">
                  Source: OpenStreetMap contributors
                </p>
              </div>
            </Popup>
          </CircleMarker>
        );
      })}

      {/* Loading indicator — small badge top-left */}
      {loading && (
        <div
          style={{
            position: 'absolute',
            top: 8,
            left: 60,
            zIndex: 1001,
            background: 'rgba(0,0,0,0.65)',
            color: '#FF6B00',
            borderRadius: 6,
            padding: '2px 8px',
            fontSize: 10,
            pointerEvents: 'none',
          }}
        >
          Loading OSM towers…
        </div>
      )}
    </>
  );
}

/* -------------------------------------------------------------------------- */
/* Map event handler: device placement + distance measure                      */
/* -------------------------------------------------------------------------- */
function MapEventHandler() {
  const tool = useMapStore((s) => s.tool);
  const addDevice = useMapStore((s) => s.addDevice);
  const selectDevice = useMapStore((s) => s.selectDevice);
  const deviceList = useMapStore((s) => s.deviceList());
  const [measureStart, setMeasureStart] = useState<[number, number] | null>(null);

  useMapEvents({
    click(e: LeafletMouseEvent) {
      const { lat, lng } = e.latlng;

      if (tool === 'select') {
        selectDevice(null);
        return;
      }

      if (tool === 'measure') {
        if (!measureStart) {
          setMeasureStart([lat, lng]);
        } else {
          const dist = haversineM(measureStart[0], measureStart[1], lat, lng);
          const km = (dist / 1000).toFixed(2);
          alert(`Distance: ${Math.round(dist)} m (${km} km)`);
          setMeasureStart(null);
        }
        return;
      }

      const kind = tool as MapDeviceKind;
      const count = deviceList.filter((d) => d.kind === kind).length + 1;

      addDevice({
        name: `${KIND_LABEL[kind]}-${count}`,
        kind,
        lat,
        lng,
        txPower: kind === 'tower' ? 27 : 20,
        frequency: 5,
        range: kind === 'tower' ? 2000 : 500,
        antennaHeight: kind === 'tower' ? 30 : 6, // metres AGL
        ip: '',
      });
    },
  });

  return null;
}

/* -------------------------------------------------------------------------- */
/* Device marker: coverage rings + circle marker + tooltip + popup            */
/* -------------------------------------------------------------------------- */
function DeviceMarker({ device }: { device: MapDevice }) {
  const selectDevice = useMapStore((s) => s.selectDevice);
  const selectedId = useMapStore((s) => s.selectedDeviceId);
  const isSelected = selectedId === device.id;
  const color = KIND_COLOR[device.kind];

  return (
    <>
      {/* Coverage gradient rings (AP and Tower only) */}
      {device.kind !== 'cpe' &&
        COVERAGE_RINGS.map((ring) => (
          <Circle
            key={ring.pct}
            center={[device.lat, device.lng]}
            radius={device.range * ring.pct}
            pathOptions={{
              color: ring.color,
              fillColor: ring.color,
              fillOpacity: ring.opacity,
              opacity: ring.opacity * 1.6,
              weight: 1,
              interactive: false,
            }}
          />
        ))}

      {/* Device dot */}
      <CircleMarker
        center={[device.lat, device.lng]}
        radius={isSelected ? 14 : 10}
        pathOptions={{
          color: isSelected ? '#FFFFFF' : color,
          fillColor: color,
          fillOpacity: 0.92,
          weight: isSelected ? 3 : 2,
        }}
        eventHandlers={{
          click: (e) => {
            L.DomEvent.stopPropagation(e);
            selectDevice(device.id);
          },
        }}
      >
        {/* Permanent name label above the dot */}
        <Tooltip permanent direction="top" offset={[0, -14]} className="nf-map-label">
          <span style={{ color, fontWeight: 700, fontSize: 10 }}>
            {device.name}
          </span>
        </Tooltip>

        {/* Click popup with full info */}
        <Popup>
          <div className="min-w-[160px] space-y-1.5 p-1">
            <p className="text-sm font-bold" style={{ color }}>
              {device.name}
            </p>
            <p className="text-xs text-gray-600">
              {device.kind.toUpperCase()} · {device.frequency} GHz · {device.txPower} dBm TX
            </p>
            <p className="text-xs text-gray-500">
              Antenna: {device.antennaHeight} m AGL · Range: {device.range} m
            </p>
            <p className="font-mono text-[10px] text-gray-400">
              {device.lat.toFixed(6)}, {device.lng.toFixed(6)}
            </p>
            {device.ip && (
              <p className="font-mono text-xs font-semibold text-blue-600">{device.ip}</p>
            )}
          </div>
        </Popup>
      </CircleMarker>
    </>
  );
}

/* -------------------------------------------------------------------------- */
/* Link polyline with LOS-aware styling                                        */
/* -------------------------------------------------------------------------- */
function LinkPolyline({
  link, from, to,
}: {
  link: MapLink;
  from: MapDevice;
  to: MapDevice;
}) {
  const color = linkColor(link);
  const dashArray = losDashArray(link.los);
  const effectiveRssi = link.rssi - link.obstructionDb;

  const losLabel =
    link.los === 'clear' ? 'Line of sight: Clear ✓' :
    link.los === 'partial' ? 'Partial Fresnel obstruction ⚠' :
    link.los === 'blocked' ? 'LOS blocked ✗' :
    'LOS unknown (checking…)';

  return (
    <Polyline
      positions={[
        [from.lat, from.lng],
        [to.lat, to.lng],
      ]}
      pathOptions={{
        color,
        weight: link.los === 'blocked' ? 2 : 2.5,
        opacity: link.los === 'blocked' ? 0.7 : 0.9,
        dashArray,
      }}
    >
      <Popup>
        <div className="min-w-[180px] space-y-1.5 p-1">
          <p className="text-sm font-bold" style={{ color }}>
            RSSI: {effectiveRssi.toFixed(1)} dBm
          </p>
          <div className="text-xs text-gray-600 space-y-0.5">
            <p>Distance: {link.distance.toLocaleString()} m</p>
            <p>FSPL RSSI: {link.rssi.toFixed(1)} dBm</p>
            {link.rainDb > 0 && <p>Rain fade: −{link.rainDb.toFixed(1)} dB</p>}
            {link.obstructionDb > 0 && <p>Terrain loss: −{link.obstructionDb.toFixed(1)} dB</p>}
            <p>Fresnel r₁: {link.fresnelM} m</p>
          </div>
          <p
            className="text-xs font-medium"
            style={{
              color:
                link.los === 'clear' ? '#34C759' :
                link.los === 'partial' ? '#FFCC00' :
                link.los === 'blocked' ? '#FF453A' :
                '#8E8E93',
            }}
          >
            {losLabel}
          </p>
          <p className="text-[10px] text-gray-400">
            {from.name} → {to.name}
          </p>
        </div>
      </Popup>
    </Polyline>
  );
}

/* -------------------------------------------------------------------------- */
/* Signal legend                                                               */
/* -------------------------------------------------------------------------- */
function SignalLegend() {
  const rainRate = useMapStore((s) => s.rainRate);
  const checkingLos = useMapStore((s) => s.checkingLos);
  const triggerLosCheck = useMapStore((s) => s.triggerLosCheck);

  return (
    <div className="pointer-events-auto absolute bottom-10 right-4 z-[1000] space-y-2">
      {/* LOS check button */}
      <button
        onClick={() => void triggerLosCheck()}
        disabled={checkingLos}
        className="flex w-full items-center justify-center gap-1.5 rounded-lg border border-white/15 bg-black/60 px-3 py-1.5 text-xs text-white/70 backdrop-blur transition-colors hover:border-accent/40 hover:text-accent disabled:cursor-not-allowed disabled:opacity-50"
      >
        {checkingLos ? (
          <>
            <span className="inline-block h-2.5 w-2.5 animate-spin rounded-full border-2 border-white/30 border-t-white/80" />
            Checking LOS…
          </>
        ) : (
          'Check Line of Sight'
        )}
      </button>

      {/* Signal legend */}
      <div className="rounded-xl border border-white/15 bg-black/60 px-3 py-2 shadow-glass backdrop-blur">
        <p className="mb-1.5 text-[9px] font-semibold uppercase tracking-wider text-white/40">
          Signal Quality
        </p>
        <div className="flex flex-col gap-0.5">
          {[
            { label: 'Strong', color: '#34C759', range: '> −55 dBm' },
            { label: 'Good',   color: '#A3E635', range: '−55 to −70' },
            { label: 'Fair',   color: '#FFCC00', range: '−70 to −80' },
            { label: 'Weak',   color: '#FF453A', range: '< −80 dBm' },
          ].map(({ label, color, range }) => (
            <div key={label} className="flex items-center gap-2">
              <span className="h-2 w-5 rounded-sm" style={{ background: color }} />
              <span className="text-[10px] text-white/70">{label}</span>
              <span className="ml-auto text-[9px] text-white/35">{range}</span>
            </div>
          ))}
        </div>

        <div className="my-1.5 border-t border-white/10" />

        <p className="mb-1 text-[9px] font-semibold uppercase tracking-wider text-white/40">
          LOS Status
        </p>
        <div className="flex flex-col gap-0.5">
          {[
            { label: 'Clear', dash: 'solid', color: '#34C759' },
            { label: 'Partial', dash: 'dashed', color: '#FFCC00' },
            { label: 'Blocked', dash: 'dotted', color: '#FF453A' },
          ].map(({ label, dash, color }) => (
            <div key={label} className="flex items-center gap-2">
              <span
                className="h-0.5 w-5"
                style={{
                  background: color,
                  borderTop: `2px ${dash} ${color}`,
                  height: 0,
                  display: 'block',
                }}
              />
              <span className="text-[10px] text-white/70">{label}</span>
            </div>
          ))}
        </div>

        {/* Weather indicator */}
        {rainRate > 0 && (
          <>
            <div className="my-1.5 border-t border-white/10" />
            <div className="flex items-center gap-1.5">
              <span className="text-xs">🌧</span>
              <span className="text-[10px] text-blue-300">
                {rainRateLabel(rainRate)} ({rainRate} mm/hr)
              </span>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Cursor hint strip (bottom center)                                           */
/* -------------------------------------------------------------------------- */
const TOOL_HINTS: Record<string, string> = {
  select: 'Click a device to select it • Delete key removes selected device',
  ap: 'Click the map to place an Access Point (coverage rings shown)',
  cpe: 'Click the map to place a CPE client — auto-connects to nearest AP',
  tower: 'Click the map to place a Tower / relay node',
  measure: 'Click two points to measure distance',
};

function ToolHint() {
  const tool = useMapStore((s) => s.tool);
  return (
    <div className="pointer-events-none absolute bottom-6 left-1/2 z-[1000] -translate-x-1/2">
      <div className="rounded-full border border-white/15 bg-black/55 px-4 py-1.5 text-xs text-white/55 shadow-glass backdrop-blur">
        {TOOL_HINTS[tool] ?? ''}
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Weather bar (top-center, only when rain > 0)                               */
/* -------------------------------------------------------------------------- */
function WeatherBar() {
  const rainRate = useMapStore((s) => s.rainRate);
  if (rainRate === 0) return null;
  return (
    <div className="pointer-events-none absolute left-1/2 top-4 z-[1000] -translate-x-1/2">
      <div className="flex items-center gap-2 rounded-full border border-blue-400/30 bg-blue-900/60 px-4 py-1.5 text-xs text-blue-200 backdrop-blur">
        <span>🌧</span>
        <span>
          {rainRateLabel(rainRate)} — {rainRate} mm/hr · Rain fade active
        </span>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Main MapView                                                                */
/* -------------------------------------------------------------------------- */
export function MapView() {
  const devices = useMapStore((s) => s.deviceList());
  const links = useMapStore((s) => s.linkList());
  const mapCenter = useMapStore((s) => s.mapCenter);
  const mapZoom = useMapStore((s) => s.mapZoom);
  const showOnboarding = useMapStore((s) => s.showOnboarding);
  const devById = useMapStore((s) => s.devices);

  return (
    <div className="relative h-full w-full overflow-hidden">
      <MapContainer
        center={mapCenter}
        zoom={mapZoom}
        zoomControl={false}
        className="h-full w-full"
        style={{ background: '#0d1117' }}
      >
        {/* Esri World Imagery — free satellite tiles, no API key */}
        <TileLayer
          url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
          attribution="Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community"
          maxZoom={19}
        />

        {/* CARTO dark label overlay for readability */}
        <TileLayer
          url="https://{s}.basemaps.cartocdn.com/dark_only_labels/{z}/{x}/{y}{r}.png"
          attribution='&copy; <a href="https://carto.com/">CARTO</a>'
          opacity={0.75}
          maxZoom={19}
        />

        <ZoomControl position="bottomright" />

        {/* Map interaction */}
        <MapEventHandler />

        {/* OSM existing telecom towers — fetched from Overpass API */}
        <OsmTowerLayer />

        {/* Links — rendered before devices so devices appear on top */}
        {links.map((link) => {
          const from = devById.get(link.fromId);
          const to = devById.get(link.toId);
          if (!from || !to) return null;
          return (
            <LinkPolyline key={link.id} link={link} from={from} to={to} />
          );
        })}

        {/* Device markers with coverage rings */}
        {devices.map((dev) => (
          <DeviceMarker key={dev.id} device={dev} />
        ))}
      </MapContainer>

      {/* Overlay UI */}
      <MapToolbar />
      <MapDevicePanel />
      <SignalLegend />
      <ToolHint />
      <WeatherBar />

      {/* First-run modal */}
      {showOnboarding && <MapOnboardingModal />}
    </div>
  );
}
