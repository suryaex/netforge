"""Terrain elevation provider + line-of-sight analysis service.

Fetches a sampled elevation profile between two WGS84 points from a public
elevation API (open-elevation by default) and feeds it to the engine's
``line_of_sight`` / Fresnel analysis. The provider call is **best-effort and
sandboxed**:

  * hard request timeout (no hanging the event loop),
  * the host is pinned to an allowlisted provider (no SSRF: callers cannot point
    this at arbitrary internal hosts),
  * on any failure it raises :class:`ElevationUnavailable` so the API layer can
    return a clean 503 instead of leaking a stack trace.

For fully offline / deterministic use, callers may pass a pre-fetched profile to
the LoS endpoint and skip the network entirely.
"""
from __future__ import annotations

import logging

import httpx

from engine import wireless as rf

logger = logging.getLogger("netforge.elevation")

# Allowlisted provider — pinned to avoid SSRF via a user-supplied base URL.
_PROVIDER_URL = "https://api.open-elevation.com/api/v1/lookup"
_TIMEOUT_S = 8.0
_MAX_SAMPLES = 128


class ElevationUnavailable(RuntimeError):
    """The elevation provider could not be reached / returned bad data."""


def _interpolate_points(
    a_lat: float, a_lon: float, b_lat: float, b_lon: float, samples: int
) -> list[tuple[float, float, float]]:
    """Evenly-spaced (lat, lon, distance_from_a_m) samples along the great line."""
    samples = max(2, min(samples, _MAX_SAMPLES))
    total = rf.haversine_m(a_lat, a_lon, b_lat, b_lon)
    out: list[tuple[float, float, float]] = []
    for i in range(samples):
        t = i / (samples - 1)
        lat = a_lat + (b_lat - a_lat) * t
        lon = a_lon + (b_lon - a_lon) * t
        out.append((lat, lon, total * t))
    return out


async def fetch_profile(
    a_lat: float, a_lon: float, b_lat: float, b_lon: float, samples: int = 24
) -> list[dict]:
    """Return a list of ``{lat, lon, elevation_m, distance_m}`` along the path.

    Raises :class:`ElevationUnavailable` on network / provider errors.
    """
    pts = _interpolate_points(a_lat, a_lon, b_lat, b_lon, samples)
    locations = [{"latitude": lat, "longitude": lon} for lat, lon, _ in pts]
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            resp = await client.post(_PROVIDER_URL, json={"locations": locations})
            resp.raise_for_status()
            results = resp.json().get("results", [])
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("elevation provider unavailable: %s", exc)
        raise ElevationUnavailable(str(exc)) from exc

    if len(results) != len(pts):
        raise ElevationUnavailable("elevation provider returned mismatched length")

    return [
        {
            "lat": pts[i][0],
            "lon": pts[i][1],
            "elevation_m": float(results[i].get("elevation", 0.0)),
            "distance_m": round(pts[i][2], 2),
        }
        for i in range(len(pts))
    ]


def analyse_los(
    distance_m: float,
    frequency_ghz: float,
    tx_height_m: float,
    rx_height_m: float,
    profile: list[dict],
) -> rf.LosResult:
    """Run the engine LoS/Fresnel analysis over a ``{distance_m, elevation_m}``
    profile (as produced by :func:`fetch_profile` or supplied by the caller)."""
    samples = [(p["distance_m"], p["elevation_m"]) for p in profile]
    samples.sort(key=lambda s: s[0])
    return rf.line_of_sight(
        distance_m=distance_m,
        freq_hz=frequency_ghz * 1e9,
        tx_height_m=tx_height_m,
        rx_height_m=rx_height_m,
        profile=samples,
    )


__all__ = ["fetch_profile", "analyse_los", "ElevationUnavailable", "_PROVIDER_URL"]
