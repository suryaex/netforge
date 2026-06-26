/**
 * OSM Service — Overpass API integration for OpenStreetMap data.
 *
 * Fetches real-world telecom infrastructure (towers, BTS, masts) from
 * the OpenStreetMap database via the public Overpass API.
 *
 * No API key required. Rate-limited by Overpass policy (max ~10 req/min).
 * Results are cached per bounding box to avoid duplicate fetches during
 * map pan/zoom.
 *
 * OSM tag references:
 *   https://wiki.openstreetmap.org/wiki/Tag:tower:type%3Dcommunication
 *   https://wiki.openstreetmap.org/wiki/Tag:man_made%3Dmast
 *   https://wiki.openstreetmap.org/wiki/Tag:man_made%3Dtower
 */

const OVERPASS_URL = 'https://overpass-api.de/api/interpreter';
const CACHE = new Map<string, OsmTower[]>();

export interface OsmTower {
  id: number;
  lat: number;
  lng: number;
  /** OSM tags — may be partial depending on contributor detail */
  tags: {
    name?: string;
    'tower:type'?: string;
    'man_made'?: string;
    operator?: string;
    height?: string;
    'communication:mobile_phone'?: string;
    'communication:radio'?: string;
    'communication:microwave'?: string;
    ref?: string;
    note?: string;
  };
}

/** Round bounding box to 2 decimal places (~1 km grid) for cache bucketing. */
function bboxKey(south: number, west: number, north: number, east: number): string {
  const r = (n: number) => Math.round(n * 100) / 100;
  return `${r(south)},${r(west)},${r(north)},${r(east)}`;
}

/**
 * Build an Overpass QL query that fetches telecom towers and communication
 * masts within a bounding box. Combines multiple tag strategies so results
 * include both formally tagged BTS nodes and generic communication towers.
 */
function buildQuery(south: number, west: number, north: number, east: number): string {
  const bbox = `${south},${west},${north},${east}`;
  return `
[out:json][timeout:25];
(
  node["tower:type"="communication"](${bbox});
  node["man_made"="mast"]["communication"](${bbox});
  node["man_made"="tower"]["tower:type"="communication"](${bbox});
  node["man_made"="mast"]["tower:type"="communication"](${bbox});
  node["communication:mobile_phone"="yes"](${bbox});
  node["man_made"="mast"]["operator"](${bbox});
);
out body;
`.trim();
}

interface OverpassElement {
  type: string;
  id: number;
  lat: number;
  lon: number;
  tags?: Record<string, string>;
}

interface OverpassResponse {
  elements: OverpassElement[];
}

/**
 * Fetch telecom towers from OpenStreetMap within the given bounding box.
 *
 * @param south  - southern latitude bound
 * @param west   - western longitude bound
 * @param north  - northern latitude bound
 * @param east   - eastern longitude bound
 * @returns      - array of OsmTower objects (empty on error)
 */
export async function fetchOsmTowers(
  south: number,
  west: number,
  north: number,
  east: number,
): Promise<OsmTower[]> {
  const key = bboxKey(south, west, north, east);
  const cached = CACHE.get(key);
  if (cached !== undefined) return cached;

  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 20_000);

    const resp = await fetch(OVERPASS_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: `data=${encodeURIComponent(buildQuery(south, west, north, east))}`,
      signal: controller.signal,
    });
    clearTimeout(timeout);

    if (!resp.ok) throw new Error(`Overpass HTTP ${resp.status}`);

    const data = (await resp.json()) as OverpassResponse;

    const towers: OsmTower[] = data.elements
      .filter((el) => el.type === 'node' && el.lat !== undefined && el.lon !== undefined)
      .map((el) => ({
        id: el.id,
        lat: el.lat,
        lng: el.lon,
        tags: (el.tags ?? {}) as OsmTower['tags'],
      }));

    CACHE.set(key, towers);
    return towers;
  } catch {
    // Network error, Overpass timeout, or rate-limit — return empty so the
    // map degrades gracefully without a blocking error.
    return [];
  }
}

/**
 * Derive a human-readable label for a tower from its OSM tags.
 * Falls back to generic "BTS" when tags are sparse.
 */
export function towerLabel(tower: OsmTower): string {
  const { tags } = tower;
  if (tags.name) return tags.name;
  if (tags.ref) return `BTS-${tags.ref}`;
  if (tags.operator) return `${tags.operator} Tower`;
  if (tags['tower:type'] === 'communication') return 'Comm. Tower';
  if (tags['man_made'] === 'mast') return 'Telecom Mast';
  return 'BTS';
}

/**
 * Classify a tower into a display category based on OSM tags.
 */
export type OsmTowerKind = 'bts' | 'mast' | 'microwave' | 'broadcast';

export function towerKind(tower: OsmTower): OsmTowerKind {
  const { tags } = tower;
  if (tags['communication:microwave'] === 'yes') return 'microwave';
  if (tags['communication:mobile_phone'] === 'yes') return 'bts';
  if (tags['communication:radio'] === 'yes') return 'broadcast';
  if (tags['man_made'] === 'mast') return 'mast';
  return 'bts';
}

/** Invalidate the OSM cache (useful for forced refresh). */
export function clearOsmCache(): void {
  CACHE.clear();
}
