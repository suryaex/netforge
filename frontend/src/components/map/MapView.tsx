/**
 * MapView — satellite map-based network design view (UISP Design Center style).
 *
 * Features:
 *  - Esri World Imagery satellite tiles via react-leaflet
 *  - Click-to-place devices (AP, CPE, Tower) with the active tool
 *  - Signal coverage rings (strong→weak gradient via concentric circles)
 *  - Links drawn as polylines colored by RSSI quality
 *  - Tooltip on hover showing RSSI + distance
 *  - Left toolbar (MapToolbar) + right properties panel (MapDevicePanel)
 *  - Welcome onboarding modal (MapOnboardingModal)
 *  - Distance measure tool
 */
import 'leaflet/dist/leaflet.css';
import { useState } from 'react';
import {
  MapContainer,
  TileLayer,
  Circle,
  Polyline,
  CircleMarker,
  Popup,
  Tooltip,
  useMapEvents,
  ZoomControl,
} from 'react-leaflet';
import type { LeafletMouseEvent } from 'leaflet';
import L from 'leaflet';
import { useMapStore, rssiColor, haversineM, type MapDevice, type MapDeviceKind } from '@/store/mapStore';
import { MapToolbar } from './MapToolbar';
import { MapDevicePanel } from './MapDevicePanel';
import { MapOnboardingModal } from './MapOnboardingModal';

// Fix default marker icon path issue with bundlers.
// We use CircleMarker instead of Marker so this is just a safety measure.
delete (L.Icon.Default.prototype as unknown as Record<string, unknown>)['_getIconUrl'];
L.Icon.Default.mergeOptions({ iconUrl: '', iconRetinaUrl: '', shadowUrl: '' });

/* -------------------------------------------------------------------------- */
/* Signal coverage color stops (strong→weak)                                   */
/* -------------------------------------------------------------------------- */
const COVERAGE_RINGS = [
  { pct: 0.25, color: '#34C759', opacity: 0.18 }, // strong (25% radius)
  { pct: 0.5,  color: '#A3E635', opacity: 0.12 }, // good
  { pct: 0.75, color: '#FFCC00', opacity: 0.09 }, // fair
  { pct: 1.0,  color: '#FF453A', opacity: 0.06 }, // weak (edge)
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
/* Sub-component: handles map events (click to place device / measure)         */
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
          alert(`Distance: ${Math.round(dist)} m (${(dist / 1000).toFixed(2)} km)`);
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
        ip: '',
      });
    },
  });

  return null;
}

/* -------------------------------------------------------------------------- */
/* Sub-component: renders a single device marker with coverage rings           */
/* -------------------------------------------------------------------------- */
function DeviceMarker({ device }: { device: MapDevice }) {
  const selectDevice = useMapStore((s) => s.selectDevice);
  const selectedId = useMapStore((s) => s.selectedDeviceId);
  const isSelected = selectedId === device.id;
  const color = KIND_COLOR[device.kind];

  return (
    <>
      {/* Coverage rings — only for AP and Tower */}
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
              opacity: ring.opacity * 1.5,
              weight: 1,
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
        {/* Always-visible name label */}
        <Tooltip permanent direction="top" offset={[0, -12]} className="nf-map-label">
          <span style={{ color, fontWeight: 600, fontSize: 11 }}>{device.name}</span>
        </Tooltip>

        <Popup className="nf-map-popup">
          <div className="min-w-[140px] space-y-1 rounded-lg p-1 text-sm">
            <p className="font-semibold" style={{ color }}>
              {device.name}
            </p>
            <p className="text-xs text-gray-600">
              {device.kind.toUpperCase()} · {device.frequency} GHz · {device.txPower} dBm
            </p>
            <p className="font-mono text-xs text-gray-500">
              {device.lat.toFixed(5)}, {device.lng.toFixed(5)}
            </p>
            {device.ip && <p className="font-mono text-xs text-blue-600">{device.ip}</p>}
          </div>
        </Popup>
      </CircleMarker>

    </>
  );
}

/* -------------------------------------------------------------------------- */
/* Sub-component: renders a link polyline with RSSI tooltip                    */
/* -------------------------------------------------------------------------- */
function LinkLine({
  fromLat, fromLng, toLat, toLng, rssi, distance,
}: {
  fromLat: number;
  fromLng: number;
  toLat: number;
  toLng: number;
  rssi: number;
  distance: number;
}) {
  const color = rssiColor(rssi);
  return (
    <Polyline
      positions={[
        [fromLat, fromLng],
        [toLat, toLng],
      ]}
      pathOptions={{ color, weight: 2.5, opacity: 0.85, dashArray: '0' }}
    >
      <Popup>
        <div className="space-y-1 text-sm">
          <p className="font-semibold" style={{ color }}>
            RSSI: {rssi} dBm
          </p>
          <p className="text-xs text-gray-600">Distance: {distance} m</p>
        </div>
      </Popup>
    </Polyline>
  );
}

/* -------------------------------------------------------------------------- */
/* Signal legend (bottom right)                                                */
/* -------------------------------------------------------------------------- */
function SignalLegend() {
  return (
    <div className="absolute bottom-10 right-4 z-[1000] pointer-events-none">
      <div className="glass-strong rounded-xl border border-white/15 px-3 py-2 shadow-glass">
        <p className="mb-1.5 text-[9px] font-semibold uppercase tracking-wider text-white/40">
          Signal
        </p>
        <div className="flex flex-col gap-0.5">
          {[
            { label: 'Strong', color: '#34C759', range: '> −55 dBm' },
            { label: 'Good',   color: '#A3E635', range: '−55 to −70' },
            { label: 'Fair',   color: '#FFCC00', range: '−70 to −80' },
            { label: 'Weak',   color: '#FF453A', range: '< −80 dBm' },
          ].map(({ label, color, range }) => (
            <div key={label} className="flex items-center gap-2">
              <span
                className="h-2 w-4 rounded-sm"
                style={{ background: color }}
              />
              <span className="text-[10px] text-white/70">{label}</span>
              <span className="ml-auto text-[9px] text-white/35">{range}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Cursor hint strip (bottom center)                                           */
/* -------------------------------------------------------------------------- */
const TOOL_HINTS: Record<string, string> = {
  select: 'Click a device to select it',
  ap: 'Click the map to place an Access Point',
  cpe: 'Click the map to place a CPE client',
  tower: 'Click the map to place a Tower',
  measure: 'Click two points to measure distance',
};

function ToolHint() {
  const tool = useMapStore((s) => s.tool);
  return (
    <div className="pointer-events-none absolute bottom-10 left-1/2 z-[1000] -translate-x-1/2">
      <div className="glass rounded-full border border-white/15 px-4 py-1.5 text-xs text-white/60 shadow-glass">
        {TOOL_HINTS[tool] ?? ''}
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

  // Build a lookup for device positions used by link rendering
  const devById = useMapStore((s) => s.devices);

  return (
    <div className="relative h-full w-full overflow-hidden">
      <MapContainer
        center={mapCenter}
        zoom={mapZoom}
        zoomControl={false}
        className="h-full w-full"
        style={{ background: '#1a1a2e' }}
      >
        {/* Satellite tile layer — Esri World Imagery (free, no key required) */}
        <TileLayer
          url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
          attribution="Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community"
          maxZoom={19}
        />

        {/* OpenStreetMap labels overlay */}
        <TileLayer
          url="https://{s}.basemaps.cartocdn.com/dark_only_labels/{z}/{x}/{y}{r}.png"
          attribution='&copy; <a href="https://carto.com/">CARTO</a>'
          opacity={0.7}
        />

        <ZoomControl position="bottomright" />

        {/* Event handler for device placement */}
        <MapEventHandler />

        {/* Links */}
        {links.map((link) => {
          const from = devById.get(link.fromId);
          const to = devById.get(link.toId);
          if (!from || !to) return null;
          return (
            <LinkLine
              key={link.id}
              fromLat={from.lat}
              fromLng={from.lng}
              toLat={to.lat}
              toLng={to.lng}
              rssi={link.rssi}
              distance={link.distance}
            />
          );
        })}

        {/* Devices */}
        {devices.map((dev) => (
          <DeviceMarker key={dev.id} device={dev} />
        ))}
      </MapContainer>

      {/* Overlay UI (not inside Leaflet) */}
      <MapToolbar />
      <MapDevicePanel />
      <SignalLegend />
      <ToolHint />

      {/* Onboarding modal */}
      {showOnboarding && <MapOnboardingModal />}
    </div>
  );
}
