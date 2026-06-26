/**
 * Elevation service — wraps the Open Elevation API (free, no key required).
 * https://api.open-elevation.com
 *
 * Fetches terrain elevation in metres for a list of lat/lng pairs.
 * Includes an in-memory LRU-like cache keyed by "lat6,lng6" to avoid
 * redundant API calls when devices move slightly or links are rebuilt.
 *
 * Falls back to 0m on network error so the UI degrades gracefully rather
 * than blocking the whole signal simulation.
 */

const API_URL = 'https://api.open-elevation.com/api/v1/lookup';
const CACHE = new Map<string, number>();

/** Cache key — rounded to 5 decimal places (~1m precision). */
function cacheKey(lat: number, lng: number): string {
  return `${lat.toFixed(5)},${lng.toFixed(5)}`;
}

interface ElevationResult {
  latitude: number;
  longitude: number;
  elevation: number;
}

interface ElevationResponse {
  results: ElevationResult[];
}

/**
 * Fetch elevation for multiple points in one request.
 * Returns an array of elevation values (metres) in the same order as input.
 * On any error, returns all zeros so simulation can continue without LOS data.
 */
export async function fetchElevations(
  points: { lat: number; lng: number }[],
): Promise<number[]> {
  if (points.length === 0) return [];

  // Separate points into cached vs uncached.
  const uncached: { lat: number; lng: number; idx: number }[] = [];
  const result: number[] = new Array(points.length).fill(0);

  for (let i = 0; i < points.length; i++) {
    const { lat, lng } = points[i]!;
    const key = cacheKey(lat, lng);
    const cached = CACHE.get(key);
    if (cached !== undefined) {
      result[i] = cached;
    } else {
      uncached.push({ lat, lng, idx: i });
    }
  }

  if (uncached.length === 0) return result;

  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 8_000);

    const resp = await fetch(API_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({
        locations: uncached.map(({ lat, lng }) => ({ latitude: lat, longitude: lng })),
      }),
      signal: controller.signal,
    });
    clearTimeout(timeout);

    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

    const data = (await resp.json()) as ElevationResponse;
    for (let j = 0; j < uncached.length; j++) {
      const elev = data.results[j]?.elevation ?? 0;
      const { lat, lng, idx } = uncached[j]!;
      CACHE.set(cacheKey(lat, lng), elev);
      result[idx] = elev;
    }
  } catch {
    // Network error or timeout — leave uncached points as 0m. The LOS check
    // will assume flat terrain which is the conservative (optimistic) fallback.
  }

  return result;
}

/**
 * Sample N equally-spaced points along the great circle between two coords.
 * Includes the endpoints.
 */
export function samplePath(
  lat1: number,
  lng1: number,
  lat2: number,
  lng2: number,
  n = 12,
): { lat: number; lng: number }[] {
  const points: { lat: number; lng: number }[] = [];
  for (let i = 0; i < n; i++) {
    const t = i / (n - 1);
    points.push({ lat: lat1 + (lat2 - lat1) * t, lng: lng1 + (lng2 - lng1) * t });
  }
  return points;
}
