"""Geo-aware wireless signal propagation — the engine's RF physics core.

Like the rest of ``engine/`` this module is **pure and framework-agnostic**: no
FastAPI, no store, no I/O. It consumes plain values / dataclasses and returns
deterministic results, so it can be unit-tested in isolation and embedded
anywhere (the web layer wraps it in ``app/services/wireless.py``).

The model is a classic outdoor point-to-point / point-to-multipoint link budget:

    Pr(dBm) = Pt(dBm) + Gt(dBi) + Gr(dBi) - FSPL(dB) - Lmisc(dB)

where FSPL is the Friis free-space path loss

    FSPL(dB) = 20·log10(d_m) + 20·log10(f_Hz) - 147.55

The constant -147.55 = 20·log10(4π / c) with c = 299_792_458 m/s.

This is the *authoritative* RSSI computation for the whole platform. The
frontend keeps a lightweight FSPL estimate for instant on-drag feedback, but the
backend value (which also accounts for antenna gain, miscellaneous loss, and
receiver sensitivity / link margin) is what gets persisted and broadcast so all
clients agree.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum

# 20*log10(4*pi/c), c = speed of light in m/s. Pre-computed for the hot path.
_FSPL_CONST = 20.0 * math.log10(4.0 * math.pi / 299_792_458.0)  # ≈ -147.55
EARTH_RADIUS_M = 6_371_000.0


class LinkQuality(str, Enum):
    """Coarse RSSI buckets. Thresholds match the frontend ``rssiColor`` so the
    map legend and the engine never disagree on what 'good' means."""

    excellent = "excellent"   # >= -55 dBm
    good = "good"             # >= -70 dBm
    fair = "fair"             # >= -80 dBm
    weak = "weak"             # >= sensitivity, below -80
    unusable = "unusable"     # below receiver sensitivity (no link)


@dataclass(slots=True)
class Radio:
    """Radio/antenna characteristics of a wireless device.

    Defaults model a typical 5 GHz outdoor CPE/AP so a caller can compute a
    sensible budget without specifying every field.
    """

    tx_power_dbm: float = 20.0          # transmit power
    frequency_ghz: float = 5.8          # carrier frequency
    antenna_gain_dbi: float = 14.0      # antenna gain (tx == rx assumed here)
    bandwidth_mhz: float = 20.0         # channel width (drives thermal noise floor)
    rx_sensitivity_dbm: float = -85.0   # minimum usable received power
    misc_loss_db: float = 2.0           # cable/connector/polarization losses
    max_range_m: float | None = None    # optional hard cap on coverage radius

    def freq_hz(self) -> float:
        return self.frequency_ghz * 1e9


@dataclass(slots=True)
class LinkBudget:
    """Full result of a point-to-point link computation."""

    distance_m: float
    fspl_db: float
    rssi_dbm: float            # received signal strength at the far end
    margin_db: float           # rssi - rx_sensitivity (fade margin)
    noise_floor_dbm: float     # thermal noise for the channel bandwidth
    snr_db: float              # rssi - noise_floor
    quality: LinkQuality
    feasible: bool             # rssi >= rx_sensitivity

    def as_dict(self) -> dict:
        return {
            "distance_m": round(self.distance_m, 2),
            "fspl_db": round(self.fspl_db, 2),
            "rssi_dbm": round(self.rssi_dbm, 2),
            "margin_db": round(self.margin_db, 2),
            "noise_floor_dbm": round(self.noise_floor_dbm, 2),
            "snr_db": round(self.snr_db, 2),
            "quality": self.quality.value,
            "feasible": self.feasible,
        }


# --- geometry ---------------------------------------------------------------
def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two WGS84 points, in metres."""
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2.0) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(d_lon / 2.0) ** 2
    )
    return EARTH_RADIUS_M * 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


# --- RF primitives ----------------------------------------------------------
def fspl_db(distance_m: float, freq_hz: float) -> float:
    """Free-space path loss in dB. Clamped at 1 m to avoid log10(0)."""
    d = max(distance_m, 1.0)
    return 20.0 * math.log10(d) + 20.0 * math.log10(freq_hz) + _FSPL_CONST


def noise_floor_dbm(bandwidth_mhz: float, noise_figure_db: float = 6.0) -> float:
    """Thermal noise floor: -174 dBm/Hz + 10·log10(BW_Hz) + receiver NF."""
    bw_hz = max(bandwidth_mhz, 0.001) * 1e6
    return -174.0 + 10.0 * math.log10(bw_hz) + noise_figure_db


def rx_power_dbm(tx: Radio, rx: Radio, distance_m: float) -> float:
    """Friis received power (dBm) of a tx→rx link at ``distance_m``."""
    loss = fspl_db(distance_m, tx.freq_hz())
    return (
        tx.tx_power_dbm
        + tx.antenna_gain_dbi
        + rx.antenna_gain_dbi
        - loss
        - tx.misc_loss_db
        - rx.misc_loss_db
    )


def quality_from_rssi(rssi_dbm: float, rx_sensitivity_dbm: float) -> LinkQuality:
    if rssi_dbm < rx_sensitivity_dbm:
        return LinkQuality.unusable
    if rssi_dbm >= -55.0:
        return LinkQuality.excellent
    if rssi_dbm >= -70.0:
        return LinkQuality.good
    if rssi_dbm >= -80.0:
        return LinkQuality.fair
    return LinkQuality.weak


def link_budget(
    tx: Radio, rx: Radio, distance_m: float, rain_rate_mm_hr: float = 0.0
) -> LinkBudget:
    """Compute a full link budget for a tx→rx pair at a given distance.

    ``rain_rate_mm_hr`` optionally applies ITU-R P.838 rain attenuation on top of
    free-space loss — important above ~10 GHz where rain fade dominates the
    margin.
    """
    loss = fspl_db(distance_m, tx.freq_hz())
    rain = rain_attenuation_db(tx.frequency_ghz, rain_rate_mm_hr, distance_m)
    rssi = rx_power_dbm(tx, rx, distance_m) - rain
    nf = noise_floor_dbm(min(tx.bandwidth_mhz, rx.bandwidth_mhz))
    return LinkBudget(
        distance_m=distance_m,
        fspl_db=loss,
        rssi_dbm=rssi,
        margin_db=rssi - rx.rx_sensitivity_dbm,
        noise_floor_dbm=nf,
        snr_db=rssi - nf,
        quality=quality_from_rssi(rssi, rx.rx_sensitivity_dbm),
        feasible=rssi >= rx.rx_sensitivity_dbm,
    )


def max_range_m(tx: Radio, rx: Radio) -> float:
    """Invert the link budget: the distance at which RSSI == rx sensitivity.

    This is the *theoretical* free-space coverage radius. If the radio carries
    an explicit ``max_range_m`` cap (antenna/regulatory limit) the smaller of
    the two wins.
    """
    # Solve fspl_db(d) = Pt + Gt + Gr - Lmisc - sensitivity  for d.
    fspl_budget = (
        tx.tx_power_dbm
        + tx.antenna_gain_dbi
        + rx.antenna_gain_dbi
        - tx.misc_loss_db
        - rx.misc_loss_db
        - rx.rx_sensitivity_dbm
    )
    exponent = (fspl_budget - 20.0 * math.log10(tx.freq_hz()) - _FSPL_CONST) / 20.0
    d = 10.0 ** exponent
    cap = tx.max_range_m if tx.max_range_m is not None else math.inf
    return max(0.0, min(d, cap))


# --- planning ---------------------------------------------------------------
@dataclass(slots=True)
class GeoDevice:
    """A device placed on the map: identity + position + radio."""

    id: str
    role: str            # "ap" | "tower" | "cpe" | "client" ...
    lat: float
    lon: float
    radio: Radio = field(default_factory=Radio)


@dataclass(slots=True)
class PlannedLink:
    """A candidate wireless association produced by :func:`plan_links`."""

    a_id: str            # serving side (AP / tower)
    b_id: str            # client side (CPE / host)
    budget: LinkBudget

    def as_dict(self) -> dict:
        return {"a_id": self.a_id, "b_id": self.b_id, **self.budget.as_dict()}


# Roles that can *serve* a client (act as the upstream of a wireless link).
SERVING_ROLES = frozenset({"ap", "tower", "olt", "router", "switch"})


def plan_links(devices: list[GeoDevice]) -> list[PlannedLink]:
    """Greedy point-to-multipoint planner.

    Each non-serving device (CPE/client/host) associates with the single serving
    device that gives the strongest *feasible* RSSI. Serving-to-serving devices
    (e.g. tower↔tower backhaul) are also linked when feasible. Deterministic:
    ties broken by stronger RSSI then by id, so the same input always yields the
    same plan (required for reproducible snapshots).
    """
    serving = [d for d in devices if d.role in SERVING_ROLES]
    links: dict[tuple[str, str], PlannedLink] = {}

    for dev in devices:
        if dev.role in SERVING_ROLES and dev.role not in ("ap", "tower"):
            # pure infra (router/switch/olt) doesn't originate a wireless assoc
            continue

        best: PlannedLink | None = None
        for srv in serving:
            if srv.id == dev.id:
                continue
            # avoid double-counting: a tower associating to an AP is fine, but a
            # plain AP shouldn't re-link to a tower it already serves. Skip pairs
            # where both are serving and we'd duplicate the reverse edge.
            dist = haversine_m(dev.lat, dev.lon, srv.lat, srv.lon)
            budget = link_budget(srv.radio, dev.radio, dist)
            if not budget.feasible:
                continue
            cand = PlannedLink(a_id=srv.id, b_id=dev.id, budget=budget)
            if best is None or _better(cand, best):
                best = cand

        if best is not None:
            key = tuple(sorted((best.a_id, best.b_id)))  # type: ignore[assignment]
            existing = links.get(key)
            if existing is None or _better(best, existing):
                links[key] = best

    # stable ordering for reproducible output
    return sorted(links.values(), key=lambda p: (p.a_id, p.b_id))


def _better(a: PlannedLink, b: PlannedLink) -> bool:
    if a.budget.rssi_dbm != b.budget.rssi_dbm:
        return a.budget.rssi_dbm > b.budget.rssi_dbm
    return (a.a_id, a.b_id) < (b.a_id, b.b_id)


# --- Fresnel zone & line-of-sight ------------------------------------------
_C = 299_792_458.0  # speed of light, m/s


def fresnel_radius_m(d1_m: float, d2_m: float, freq_hz: float, n: int = 1) -> float:
    """Radius of the n-th Fresnel zone at a point ``d1``/``d2`` from each end.

    r_n = sqrt( n · λ · d1 · d2 / (d1 + d2) ),  λ = c / f.
    Returns 0 at either endpoint (d1 or d2 == 0).
    """
    total = d1_m + d2_m
    if total <= 0 or d1_m <= 0 or d2_m <= 0:
        return 0.0
    lam = _C / freq_hz
    return math.sqrt(n * lam * d1_m * d2_m / total)


@dataclass(slots=True)
class LosResult:
    """Outcome of a terrain line-of-sight / Fresnel analysis."""

    los_clear: bool              # no terrain crosses the optical LoS line
    fresnel_clear: bool          # terrain stays out of 60% of the 1st Fresnel zone
    worst_obstruction_m: float   # max terrain intrusion above the LoS line (m; <0 = clearance)
    min_clearance_ratio: float   # min (clearance / fresnel_radius) along the path
    distance_m: float

    def as_dict(self) -> dict:
        return {
            "los_clear": self.los_clear,
            "fresnel_clear": self.fresnel_clear,
            "worst_obstruction_m": round(self.worst_obstruction_m, 2),
            "min_clearance_ratio": round(self.min_clearance_ratio, 3),
            "distance_m": round(self.distance_m, 2),
        }


def line_of_sight(
    distance_m: float,
    freq_hz: float,
    tx_height_m: float,
    rx_height_m: float,
    profile: list[tuple[float, float]],
    clearance_fraction: float = 0.6,
) -> LosResult:
    """Analyse terrain clearance between two antennas.

    ``profile`` is a list of ``(distance_from_tx_m, ground_elevation_m)`` samples
    ordered from the tx end to the rx end (inclusive of both ends). ``tx_height``
    / ``rx_height`` are antenna heights *above* the ground at their endpoints.

    The optical LoS is the straight line between antenna tips (accounting for the
    differing ground elevations at each end). At every sample we compare terrain
    against (a) that line for plain LoS, and (b) the line minus the required
    Fresnel clearance (default 60% of the first zone) for a usable RF path.
    """
    if not profile or distance_m <= 0:
        return LosResult(True, True, -math.inf, math.inf, distance_m)

    tx_amsl = profile[0][1] + tx_height_m
    rx_amsl = profile[-1][1] + rx_height_m

    worst = -math.inf
    min_ratio = math.inf
    fresnel_clear = True
    los_clear = True

    for d1, ground in profile:
        d1 = max(0.0, min(d1, distance_m))
        d2 = distance_m - d1
        # height of the optical LoS line above sea level at this point
        los_amsl = tx_amsl + (rx_amsl - tx_amsl) * (d1 / distance_m)
        intrusion = ground - los_amsl       # >0 => terrain above the LoS line
        worst = max(worst, intrusion)
        if intrusion > 0:
            los_clear = False

        r = fresnel_radius_m(d1, d2, freq_hz)
        clearance = los_amsl - ground       # vertical gap from terrain to LoS line
        if r > 0:
            ratio = clearance / r
            min_ratio = min(min_ratio, ratio)
            if ratio < clearance_fraction:
                fresnel_clear = False

    return LosResult(
        los_clear=los_clear,
        fresnel_clear=fresnel_clear,
        worst_obstruction_m=worst,
        min_clearance_ratio=min_ratio,
        distance_m=distance_m,
    )


# --- ITU-R P.838 rain attenuation ------------------------------------------
# Coefficients (horizontal polarization) for the specific attenuation model
#   γ_R = k · R^α   [dB/km]
# sampled at the reference frequencies of Rec. ITU-R P.838-3. We log-log
# interpolate in frequency between table rows — adequate for link planning.
_P838_F_GHZ = [1, 2, 4, 6, 7, 8, 10, 12, 15, 20, 25, 30, 40, 50, 60, 70, 80, 90, 100]
_P838_K = [
    0.0000259, 0.0000847, 0.0001071, 0.000302, 0.000454, 0.000650, 0.00101,
    0.00188, 0.00367, 0.00751, 0.01240, 0.01870, 0.04330, 0.0780, 0.1250,
    0.1870, 0.2630, 0.3500, 0.4400,
]
_P838_A = [
    0.9691, 1.0664, 1.6009, 1.5900, 1.4750, 1.3795, 1.2760, 1.2170, 1.1540,
    1.0990, 1.0610, 1.0210, 0.9390, 0.8500, 0.8020, 0.7790, 0.7610, 0.7530,
    0.7430,
]


def _interp_loglog(x: float, xs: list[float], ys: list[float]) -> float:
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    for i in range(1, len(xs)):
        if x <= xs[i]:
            lx0, lx1 = math.log10(xs[i - 1]), math.log10(xs[i])
            ly0, ly1 = math.log10(ys[i - 1]), math.log10(ys[i])
            t = (math.log10(x) - lx0) / (lx1 - lx0)
            return 10.0 ** (ly0 + t * (ly1 - ly0))
    return ys[-1]


def rain_specific_attenuation_db_km(freq_ghz: float, rain_rate_mm_hr: float) -> float:
    """ITU-R P.838 specific rain attenuation γ_R = k·R^α  [dB/km]."""
    if rain_rate_mm_hr <= 0 or freq_ghz <= 0:
        return 0.0
    k = _interp_loglog(freq_ghz, _P838_F_GHZ, _P838_K)
    a = _interp_loglog(freq_ghz, _P838_F_GHZ, _P838_A)
    return k * (rain_rate_mm_hr ** a)


def rain_attenuation_db(freq_ghz: float, rain_rate_mm_hr: float, distance_m: float) -> float:
    """Total rain attenuation over a path of ``distance_m`` metres (dB)."""
    return rain_specific_attenuation_db_km(freq_ghz, rain_rate_mm_hr) * (distance_m / 1000.0)
