/**
 * Signal simulation engine — field-realistic RF calculations for the map view.
 *
 * Models implemented:
 *  - Free Space Path Loss (FSPL) — baseline RSSI
 *  - ITU-R P.838 rain attenuation (simplified, single polarisation)
 *  - Fresnel zone clearance (1st zone at midpoint)
 *  - Line-of-sight (LOS) check using sampled elevation profile
 *  - Earth-curvature correction for long paths
 *
 * All inputs / outputs in SI units unless noted.
 */
import { fetchElevations, samplePath } from './elevation';

/* -------------------------------------------------------------------------- */
/* Constants                                                                   */
/* -------------------------------------------------------------------------- */
const SPEED_OF_LIGHT = 3e8; // m/s
const EARTH_RADIUS = 6_371_000; // m

/* -------------------------------------------------------------------------- */
/* 1. Free Space Path Loss (already in mapStore, duplicated here for ref)      */
/* -------------------------------------------------------------------------- */
export function fspl(distanceM: number, freqGhz: number): number {
  if (distanceM < 1) return 0;
  return (
    20 * Math.log10(distanceM) + 20 * Math.log10(freqGhz * 1e9) - 147.55
  );
}

/* -------------------------------------------------------------------------- */
/* 2. Rain attenuation (ITU-R P.838-3, simplified)                            */
/* -------------------------------------------------------------------------- */

/** k and alpha coefficients for horizontal polarisation (typical ISP link). */
const RAIN_COEFFS: Record<number, [number, number]> = {
  2.4: [0.0001071, 1.6009],
  5:   [0.0091,    1.217],
  5.8: [0.01282,   1.1695],
  10:  [0.04891,   1.0688],
  24:  [0.3171,    0.8545],
  60:  [6.77,      0.6700],
};

/**
 * Rain-specific attenuation in dB for a given link.
 * @param rainRateMmHr - Rain rate in mm/hr (0 = clear sky)
 * @param distanceM    - Link distance in metres
 * @param freqGhz      - Carrier frequency in GHz
 */
export function rainAttenuation(
  rainRateMmHr: number,
  distanceM: number,
  freqGhz: number,
): number {
  if (rainRateMmHr <= 0) return 0;

  // Find nearest frequency coefficients.
  const keys = Object.keys(RAIN_COEFFS).map(Number).sort((a, b) => a - b);
  let bestKey = keys[0]!;
  for (const k of keys) {
    if (Math.abs(k - freqGhz) < Math.abs(bestKey - freqGhz)) bestKey = k;
  }
  const [k, alpha] = RAIN_COEFFS[bestKey]!;
  const distKm = distanceM / 1000;
  return k * Math.pow(rainRateMmHr, alpha) * distKm;
}

/* -------------------------------------------------------------------------- */
/* 3. Fresnel zone                                                             */
/* -------------------------------------------------------------------------- */

/**
 * First Fresnel zone radius (metres) at a point along the path.
 * d1 = distance from TX to midpoint, d2 = distance from midpoint to RX.
 */
export function fresnelRadius1(d1M: number, d2M: number, freqGhz: number): number {
  const lambda = SPEED_OF_LIGHT / (freqGhz * 1e9);
  return Math.sqrt((lambda * d1M * d2M) / (d1M + d2M));
}

/** Required clearance: 60% of 1st Fresnel zone (Fresnel-Kirchhoff criterion). */
export function requiredClearance(d1M: number, d2M: number, freqGhz: number): number {
  return 0.6 * fresnelRadius1(d1M, d2M, freqGhz);
}

/* -------------------------------------------------------------------------- */
/* 4. Earth-bulge correction at a fractional position along the path           */
/* -------------------------------------------------------------------------- */
/**
 * Effective Earth bulge in metres at fractional position `t` (0..1) along
 * a path of length `distanceM`. Uses the 4/3 Earth radius model.
 */
function earthBulge(t: number, distanceM: number): number {
  const d1 = t * distanceM;
  const d2 = (1 - t) * distanceM;
  // h_bulge = d1 * d2 / (2 * k * R_earth), k=4/3
  return (d1 * d2) / (2 * (4 / 3) * EARTH_RADIUS);
}

/* -------------------------------------------------------------------------- */
/* 5. LOS check                                                               */
/* -------------------------------------------------------------------------- */

export type LosStatus = 'clear' | 'partial' | 'blocked' | 'unknown';

export interface LosResult {
  status: LosStatus;
  /** Worst-case Fresnel clearance deficit in metres (negative = obstacle). */
  worstClearanceM: number;
  /** dB penalty from LOS obstruction (0 if clear). */
  obstructionDb: number;
}

/**
 * Check line of sight between two antenna locations.
 * @param lat1, lng1, alt1  - TX position (lat/lng in degrees, altitude in m AGL)
 * @param lat2, lng2, alt2  - RX position
 * @param distanceM         - Pre-computed great-circle distance
 * @param freqGhz           - Frequency for Fresnel zone calculation
 */
export async function checkLos(
  lat1: number,
  lng1: number,
  alt1: number, // antenna height above ground, metres
  lat2: number,
  lng2: number,
  alt2: number,
  distanceM: number,
  freqGhz: number,
): Promise<LosResult> {
  const N = 12; // number of path samples
  const path = samplePath(lat1, lng1, lat2, lng2, N);
  const elevations = await fetchElevations(path);

  // Antenna heights above sea level.
  const h1 = elevations[0]! + alt1;
  const h2 = elevations[N - 1]! + alt2;

  let worstClearance = Infinity;
  let blocked = false;
  let partial = false;

  for (let i = 1; i < N - 1; i++) {
    const t = i / (N - 1);
    const losHeight = h1 + (h2 - h1) * t; // geometric LOS height at this point
    const terrainH = elevations[i]! + earthBulge(t, distanceM);

    const d1 = t * distanceM;
    const d2 = (1 - t) * distanceM;
    const fc = requiredClearance(d1, d2, freqGhz);

    const clearance = losHeight - terrainH - fc;
    if (clearance < worstClearance) {
      worstClearance = clearance;
    }

    if (losHeight < terrainH) {
      blocked = true;
    } else if (losHeight - terrainH < fc) {
      partial = true;
    }
  }

  const status: LosStatus = blocked ? 'blocked' : partial ? 'partial' : 'clear';

  // Knife-edge diffraction loss approximation for partial/blocked (ITU-R P.526).
  // Very rough: 6 dB for partial Fresnel, 20+ dB for full blockage.
  const obstructionDb =
    status === 'blocked'
      ? 20
      : status === 'partial'
        ? Math.max(0, 6 * (1 - (worstClearance / (worstClearance + 1))))
        : 0;

  return {
    status,
    worstClearanceM: worstClearance === Infinity ? 0 : worstClearance,
    obstructionDb,
  };
}

/* -------------------------------------------------------------------------- */
/* 6. Combined RSSI with all effects                                           */
/* -------------------------------------------------------------------------- */

export interface SignalResult {
  rssi: number;        // dBm
  fsplDb: number;
  rainDb: number;
  obstructionDb: number;
  los: LosStatus;
}

export async function computeSignal(opts: {
  txPower: number;    // dBm
  distanceM: number;  // metres
  freqGhz: number;
  rainRateMmHr: number;
  lat1: number; lng1: number; altAgl1: number;
  lat2: number; lng2: number; altAgl2: number;
}): Promise<SignalResult> {
  const { txPower, distanceM, freqGhz, rainRateMmHr, lat1, lng1, altAgl1, lat2, lng2, altAgl2 } = opts;

  const fsplDb = fspl(distanceM, freqGhz);
  const rainDb = rainAttenuation(rainRateMmHr, distanceM, freqGhz);

  const losResult = await checkLos(
    lat1, lng1, altAgl1,
    lat2, lng2, altAgl2,
    distanceM, freqGhz,
  );

  const rssi = txPower - fsplDb - rainDb - losResult.obstructionDb;

  return {
    rssi: Math.round(rssi * 10) / 10,
    fsplDb: Math.round(fsplDb * 10) / 10,
    rainDb: Math.round(rainDb * 10) / 10,
    obstructionDb: losResult.obstructionDb,
    los: losResult.status,
  };
}
