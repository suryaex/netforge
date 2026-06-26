"""Terrain elevation, LOS, and Fresnel-zone analysis for NetForge.

Fetches real elevation data from the Open-Elevation public API
(https://api.open-elevation.com/api/v1/lookup) and computes:

  - **Elevation profile** along a great-circle path between two geo-points.
  - **Fresnel zone clearance** at each terrain sample.
  - **LOS (line-of-sight) check** — whether the path is obstructed by terrain.

Caching
-------
Elevation look-ups are cached in an in-process LRU dict keyed by (lat, lon)
rounded to 5 decimal places (~1 m resolution). The cache is intentionally
simple (no TTL) because elevation data is effectively permanent.  The cache
can be cleared with :func:`clear_elevation_cache`.

HTTP transport
--------------
``urllib.request`` (stdlib) is used so the module remains dependency-free.
A configurable timeout protects against slow API responses.  For async
FastAPI endpoints, run calls inside ``asyncio.get_event_loop().run_in_executor``
or use the provided :func:`async_elevation_profile` helper.

Unit conventions
----------------
- Lat/lon: decimal degrees WGS84
- Distances: metres (internally), km labelled explicitly
- Elevations: metres above MSL
- Frequencies: GHz
"""
from __future__ import annotations

import asyncio
import json
import math
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Sequence

EARTH_RADIUS_M = 6_371_000.0
OPEN_ELEVATION_URL = "https://api.open-elevation.com/api/v1/lookup"
_HTTP_TIMEOUT_S = 10.0  # per-request timeout

# ---------------------------------------------------------------------------
# In-process elevation cache: (lat5dp, lon5dp) -> elevation_m
# ---------------------------------------------------------------------------

_elev_cache: dict[tuple[float, float], float] = {}


def clear_elevation_cache() -> int:
    """Flush the in-process elevation cache.  Returns number of entries removed."""
    n = len(_elev_cache)
    _elev_cache.clear()
    return n


def _cache_key(lat: float, lon: float) -> tuple[float, float]:
    return round(lat, 5), round(lon, 5)


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance (metres) between two WGS84 points."""
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2.0) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(d_lon / 2.0) ** 2
    )
    return EARTH_RADIUS_M * 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def _interpolate_point(
    lat1: float, lon1: float, lat2: float, lon2: float, fraction: float
) -> tuple[float, float]:
    """Linear interpolation along the rhumb line (adequate for <200 km paths)."""
    lat = lat1 + fraction * (lat2 - lat1)
    lon = lon1 + fraction * (lon2 - lon1)
    return lat, lon


def _sample_path(
    lat1: float, lon1: float, lat2: float, lon2: float, n_samples: int
) -> list[tuple[float, float]]:
    """Generate ``n_samples`` evenly spaced (lat, lon) points along the path.

    Endpoints are included (indices 0 and n-1).
    """
    if n_samples < 2:
        n_samples = 2
    return [
        _interpolate_point(lat1, lon1, lat2, lon2, i / (n_samples - 1))
        for i in range(n_samples)
    ]


# ---------------------------------------------------------------------------
# Open-Elevation API fetcher
# ---------------------------------------------------------------------------

def _fetch_elevations_sync(
    points: list[tuple[float, float]],
    timeout: float = _HTTP_TIMEOUT_S,
) -> list[float]:
    """POST a batch of (lat, lon) to Open-Elevation and return elevation list.

    Cache hits are used directly; only uncached points are sent to the API.
    Results are merged back in original order.

    Args:
        points:  List of (lat, lon) tuples.
        timeout: HTTP request timeout in seconds.

    Returns:
        List of elevation_m values matching ``points`` order.

    Raises:
        urllib.error.URLError: If the API call fails.
        ValueError: If the API response is malformed.
    """
    results: list[float | None] = [None] * len(points)
    uncached_indices: list[int] = []

    # Serve from cache first
    for i, (lat, lon) in enumerate(points):
        key = _cache_key(lat, lon)
        if key in _elev_cache:
            results[i] = _elev_cache[key]
        else:
            uncached_indices.append(i)

    if uncached_indices:
        payload = {
            "locations": [
                {"latitude": points[i][0], "longitude": points[i][1]}
                for i in uncached_indices
            ]
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            OPEN_ELEVATION_URL,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))

        api_results = body.get("results", [])
        if len(api_results) != len(uncached_indices):
            raise ValueError(
                f"Open-Elevation returned {len(api_results)} results "
                f"for {len(uncached_indices)} requested points"
            )
        for order_pos, orig_idx in enumerate(uncached_indices):
            elev = float(api_results[order_pos]["elevation"])
            key = _cache_key(*points[orig_idx])
            _elev_cache[key] = elev
            results[orig_idx] = elev

    return [float(r) for r in results]  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Public data structures
# ---------------------------------------------------------------------------

@dataclass
class ElevationSample:
    """A single elevation profile sample with Fresnel clearance metadata."""
    distance_m:          float    # distance from TX (metres)
    fraction:            float    # 0.0 = TX, 1.0 = RX
    lat:                 float
    lon:                 float
    elevation_m:         float    # terrain elevation above MSL
    los_elevation_m:     float    # interpolated LoS altitude at this point
    clearance_m:         float    # los_elevation - terrain; negative = obstruction
    fresnel_radius_m:    float    # 1st Fresnel zone radius at this point
    fresnel_clearance_m: float    # clearance relative to 1st Fresnel zone


@dataclass
class LOSResult:
    """Result of a full line-of-sight and Fresnel-zone analysis."""
    tx_lat:       float
    tx_lon:       float
    rx_lat:       float
    rx_lon:       float
    tx_elevation_m: float
    rx_elevation_m: float
    tx_antenna_height_m: float
    rx_antenna_height_m: float
    distance_m:   float
    frequency_ghz: float
    has_los:      bool            # True if no terrain obstruction on geometric LoS
    fresnel_clear: bool           # True if 60 % Fresnel clearance criterion met
    obstruction_fraction: float   # 0.0 = no obstruction along path
    min_clearance_m: float        # worst-case clearance (< 0 = buried below terrain)
    min_fresnel_clearance_m: float  # worst-case 1st Fresnel clearance
    profile:      list[ElevationSample] = field(default_factory=list)

    def as_dict(self, include_profile: bool = False) -> dict:
        d: dict = {
            "tx_lat": self.tx_lat, "tx_lon": self.tx_lon,
            "rx_lat": self.rx_lat, "rx_lon": self.rx_lon,
            "distance_m": round(self.distance_m, 1),
            "frequency_ghz": self.frequency_ghz,
            "has_los": self.has_los,
            "fresnel_clear": self.fresnel_clear,
            "obstruction_fraction": round(self.obstruction_fraction, 4),
            "min_clearance_m": round(self.min_clearance_m, 1),
            "min_fresnel_clearance_m": round(self.min_fresnel_clearance_m, 1),
        }
        if include_profile:
            d["profile"] = [
                {
                    "distance_m": round(s.distance_m, 1),
                    "elevation_m": round(s.elevation_m, 1),
                    "los_elevation_m": round(s.los_elevation_m, 1),
                    "clearance_m": round(s.clearance_m, 1),
                    "fresnel_radius_m": round(s.fresnel_radius_m, 1),
                    "fresnel_clearance_m": round(s.fresnel_clearance_m, 1),
                }
                for s in self.profile
            ]
        return d


# ---------------------------------------------------------------------------
# Fresnel zone computation
# ---------------------------------------------------------------------------

def fresnel_radius_m(
    distance_from_tx_m: float,
    total_distance_m: float,
    frequency_ghz: float,
    zone: int = 1,
) -> float:
    """Radius of the nth Fresnel zone at a point along the path.

    r_n = √(n · λ · d1 · d2 / (d1 + d2))

    where d1 = distance from TX, d2 = distance from RX, λ = wavelength.

    Args:
        distance_from_tx_m: Distance from TX to the obstacle (metres).
        total_distance_m:   Total TX-to-RX path length (metres).
        frequency_ghz:      Carrier frequency (GHz).
        zone:               Fresnel zone number (default 1).

    Returns:
        Fresnel zone radius in metres.
    """
    d1 = max(distance_from_tx_m, 0.1)
    d2 = max(total_distance_m - d1, 0.1)
    lambda_m = 0.3 / frequency_ghz   # c/f in metres
    return math.sqrt(zone * lambda_m * d1 * d2 / (d1 + d2))


# ---------------------------------------------------------------------------
# Core analysis function (synchronous)
# ---------------------------------------------------------------------------

def compute_los(
    tx_lat: float,
    tx_lon: float,
    rx_lat: float,
    rx_lon: float,
    tx_antenna_height_m: float = 30.0,
    rx_antenna_height_m: float = 10.0,
    frequency_ghz: float = 5.8,
    n_samples: int = 64,
    fresnel_clearance_ratio: float = 0.6,
    api_timeout: float = _HTTP_TIMEOUT_S,
) -> LOSResult:
    """Compute elevation profile, LOS, and Fresnel clearance between two points.

    Steps:
        1. Sample ``n_samples`` equidistant points along the great-circle path.
        2. Fetch elevation from Open-Elevation API (batch POST, cached).
        3. Build a straight LoS line between TX and RX antenna radiation centres.
        4. For each terrain sample compute:
           - geometric clearance above terrain (los_elev - terrain_elev)
           - 1st Fresnel zone radius
           - Fresnel clearance (geometric_clearance - fresnel_radius)
        5. Determine has_los and fresnel_clear flags.

    Args:
        tx_lat, tx_lon:       Transmitter position (decimal degrees WGS84).
        rx_lat, rx_lon:       Receiver position.
        tx_antenna_height_m:  TX antenna AGL height (metres).
        rx_antenna_height_m:  RX antenna AGL height (metres).
        frequency_ghz:        Carrier frequency for Fresnel calculation (GHz).
        n_samples:            Number of profile samples (8–256 recommended).
        fresnel_clearance_ratio: Minimum Fresnel zone fraction required (0.6 = 60 %).
        api_timeout:          Open-Elevation API timeout (seconds).

    Returns:
        LOSResult with full profile and summary flags.

    Raises:
        urllib.error.URLError: If the elevation API call fails.
    """
    n_samples = max(8, min(n_samples, 256))
    total_m = _haversine_m(tx_lat, tx_lon, rx_lat, rx_lon)

    path_points = _sample_path(tx_lat, tx_lon, rx_lat, rx_lon, n_samples)
    elevations = _fetch_elevations_sync(path_points, timeout=api_timeout)

    tx_elev_m = elevations[0]
    rx_elev_m = elevations[-1]
    tx_rad_m = tx_elev_m + tx_antenna_height_m  # radiation centre (MSL)
    rx_rad_m = rx_elev_m + rx_antenna_height_m

    profile: list[ElevationSample] = []
    n_obstructed = 0
    min_clear = math.inf
    min_fresnel_clear = math.inf

    for i, ((lat, lon), terrain_elev) in enumerate(zip(path_points, elevations)):
        frac = i / (n_samples - 1)
        dist_m = frac * total_m

        # LoS altitude at this point (linear interpolation in MSL space)
        los_elev = tx_rad_m + frac * (rx_rad_m - tx_rad_m)
        clearance = los_elev - terrain_elev

        # Fresnel zone radius (skip endpoints)
        fr = 0.0
        fresnel_clear = clearance
        if 0 < i < n_samples - 1:
            fr = fresnel_radius_m(dist_m, total_m, frequency_ghz, zone=1)
            fresnel_clear = clearance - fr

        if clearance < min_clear:
            min_clear = clearance
        if fresnel_clear < min_fresnel_clear:
            min_fresnel_clear = fresnel_clear

        if clearance < 0:
            n_obstructed += 1

        profile.append(ElevationSample(
            distance_m=dist_m,
            fraction=frac,
            lat=lat,
            lon=lon,
            elevation_m=terrain_elev,
            los_elevation_m=los_elev,
            clearance_m=clearance,
            fresnel_radius_m=fr,
            fresnel_clearance_m=fresnel_clear,
        ))

    has_los = min_clear >= 0.0
    # Fresnel clearance criterion: min clearance >= fresnel_clearance_ratio * F1
    # Simplified: all interior points must have fresnel_clear >= 0 at the ratio
    # We already computed clearance relative to full F1 radius; scale check here.
    # "60 % Fresnel" means terrain must be at least 0.6 * F1 below the LoS.
    # Equivalently, clearance must be >= (1 - ratio) * F1 ... but we store
    # clearance - F1, so the criterion is clearance_m >= -(1 - ratio)*F1.
    # For simplicity we flag fresnel_clear based on the worst interior sample.
    fresnel_ok = all(
        s.fresnel_clearance_m >= -(1.0 - fresnel_clearance_ratio) * s.fresnel_radius_m
        if s.fresnel_radius_m > 0 else True
        for s in profile
    )

    obstruction_frac = n_obstructed / max(n_samples - 2, 1)  # exclude endpoints

    return LOSResult(
        tx_lat=tx_lat, tx_lon=tx_lon,
        rx_lat=rx_lat, rx_lon=rx_lon,
        tx_elevation_m=tx_elev_m,
        rx_elevation_m=rx_elev_m,
        tx_antenna_height_m=tx_antenna_height_m,
        rx_antenna_height_m=rx_antenna_height_m,
        distance_m=total_m,
        frequency_ghz=frequency_ghz,
        has_los=has_los,
        fresnel_clear=fresnel_ok,
        obstruction_fraction=obstruction_frac,
        min_clearance_m=min_clear if min_clear != math.inf else 0.0,
        min_fresnel_clearance_m=min_fresnel_clear if min_fresnel_clear != math.inf else 0.0,
        profile=profile,
    )


# ---------------------------------------------------------------------------
# Async wrapper for use from FastAPI endpoints
# ---------------------------------------------------------------------------

async def async_compute_los(
    tx_lat: float,
    tx_lon: float,
    rx_lat: float,
    rx_lon: float,
    tx_antenna_height_m: float = 30.0,
    rx_antenna_height_m: float = 10.0,
    frequency_ghz: float = 5.8,
    n_samples: int = 64,
    fresnel_clearance_ratio: float = 0.6,
    api_timeout: float = _HTTP_TIMEOUT_S,
) -> LOSResult:
    """Async wrapper around :func:`compute_los` — runs in a thread-pool executor
    so the FastAPI event loop is not blocked during the HTTP call."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: compute_los(
            tx_lat, tx_lon, rx_lat, rx_lon,
            tx_antenna_height_m=tx_antenna_height_m,
            rx_antenna_height_m=rx_antenna_height_m,
            frequency_ghz=frequency_ghz,
            n_samples=n_samples,
            fresnel_clearance_ratio=fresnel_clearance_ratio,
            api_timeout=api_timeout,
        ),
    )


async def async_elevation_profile(
    lat1: float, lon1: float,
    lat2: float, lon2: float,
    n_samples: int = 64,
    api_timeout: float = _HTTP_TIMEOUT_S,
) -> list[tuple[float, float, float]]:
    """Return a list of (distance_m, lat, lon, elevation_m) tuples.

    Convenience wrapper when only the raw elevation profile is needed.
    """
    loop = asyncio.get_event_loop()

    def _run() -> list[tuple[float, float, float]]:
        total_m = _haversine_m(lat1, lon1, lat2, lon2)
        path = _sample_path(lat1, lon1, lat2, lon2, n_samples)
        elevs = _fetch_elevations_sync(path, timeout=api_timeout)
        return [
            (i / (n_samples - 1) * total_m, lat, lon, elev)
            for i, ((lat, lon), elev) in enumerate(zip(path, elevs))
        ]

    return await loop.run_in_executor(None, _run)


__all__ = [
    "clear_elevation_cache",
    "fresnel_radius_m",
    "ElevationSample",
    "LOSResult",
    "compute_los",
    "async_compute_los",
    "async_elevation_profile",
    "OPEN_ELEVATION_URL",
]
