/**
 * Map tile layer configuration.
 *
 * All providers listed here are free and require no API key for standard
 * usage. Attribution strings must be preserved per each provider's ToS.
 *
 * Usage with react-leaflet:
 *   import { MAP_TILES } from '@/config/mapTiles';
 *   <TileLayer url={MAP_TILES.satellite.url} attribution={MAP_TILES.satellite.attribution} />
 */

export interface TileLayerConfig {
  url: string;
  attribution: string;
  maxZoom?: number;
  subdomains?: string;
  /** Secondary overlay layer (labels, roads) to stack on top */
  overlay?: {
    url: string;
    attribution: string;
    opacity?: number;
  };
}

export const MAP_TILES = {
  /**
   * Esri World Imagery — high-resolution satellite/aerial imagery.
   * No API key required. Suitable for ISP field design (UISP-style).
   */
  satellite: {
    url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    attribution:
      'Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community',
    maxZoom: 19,
    overlay: {
      url: 'https://{s}.basemaps.cartocdn.com/dark_only_labels/{z}/{x}/{y}{r}.png',
      attribution: '&copy; <a href="https://carto.com/">CARTO</a>',
      opacity: 0.7,
    },
  },

  /**
   * OpenStreetMap Standard — street map with roads, buildings, POIs.
   * Tile usage policy: https://operations.osmfoundation.org/policies/tiles/
   */
  street: {
    url: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    maxZoom: 19,
    subdomains: 'abc',
  },

  /**
   * Hybrid — Esri satellite base + CartoDB road/label overlay.
   * Best for combining real-world context with infrastructure planning.
   */
  hybrid: {
    url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    attribution:
      'Tiles &copy; Esri &mdash; Imagery; Roads &copy; <a href="https://carto.com/">CARTO</a>',
    maxZoom: 19,
    overlay: {
      url: 'https://{s}.basemaps.cartocdn.com/light_only_labels/{z}/{x}/{y}{r}.png',
      attribution: '&copy; <a href="https://carto.com/">CARTO</a>',
      opacity: 0.85,
    },
  },

  /**
   * CartoDB Dark Matter — dark basemap optimized for data visualization.
   * Good for signal coverage heat-map overlays.
   */
  dark: {
    url: 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/">CARTO</a>',
    maxZoom: 19,
    subdomains: 'abcd',
  },

  /**
   * OpenTopoMap — topographic map with elevation contours.
   * Useful for terrain-aware signal propagation planning.
   */
  topo: {
    url: 'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
    attribution:
      'Map data: &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, <a href="http://viewfinderpanoramas.org">SRTM</a> | Map style: &copy; <a href="https://opentopomap.org">OpenTopoMap</a> (<a href="https://creativecommons.org/licenses/by-sa/3.0/">CC-BY-SA</a>)',
    maxZoom: 17,
    subdomains: 'abc',
  },
} as const satisfies Record<string, TileLayerConfig>;

export type MapTileKey = keyof typeof MAP_TILES;

/** Default tile layer to use on first load. */
export const DEFAULT_TILE: MapTileKey = 'satellite';
