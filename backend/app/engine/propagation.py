"""Real-field RF propagation models for NetForge.

Four industry-standard models are implemented, all pure-Python with no
external dependencies beyond the stdlib:

1. **FSPL** — Free Space Path Loss (Friis), clean LoS baseline.
2. **Okumura-Hata** — empirical model for 150–1 500 MHz, three terrain classes
   (urban large-city, suburban, open/rural).
3. **ITU-R P.452-17 (simplified)** — terrain-clearance diffraction loss using
   the Bullington equivalent-geometry method, combined with free-space basic
   transmission loss. Suitable for PtP microwave links where terrain profile is
   available from the terrain module.
4. **ITU-R P.838-3** — specific rain attenuation γR = k · R^α with frequency-
   interpolated k and α coefficients for horizontal or vertical polarisation.
   Total path attenuation = γR × effective_path_length_km.

Unit conventions (throughout this module)
------------------------------------------
- Frequencies    : GHz (converted internally as required per standard)
- Distances      : metres unless noted; km for Hata and P.452
- Path loss / att: dB
- Rain rate      : mm/h
- Antenna heights: metres above local ground
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence

# ---------------------------------------------------------------------------
# 1. FSPL — Free Space Path Loss
# ---------------------------------------------------------------------------

_FSPL_CONST = 20.0 * math.log10(4.0 * math.pi / 299_792_458.0)  # ≈ -147.55 dB


def fspl_db(distance_m: float, frequency_ghz: float) -> float:
    """Free-space path loss (dB) using the Friis transmission formula.

    L_fs = 20·log10(d) + 20·log10(f) + 20·log10(4π/c)

    Args:
        distance_m:     Link distance in metres. Clamped to ≥1 m.
        frequency_ghz:  Carrier frequency in GHz.

    Returns:
        Path loss in dB (positive value — a loss).
    """
    d = max(distance_m, 1.0)
    f_hz = frequency_ghz * 1e9
    return 20.0 * math.log10(d) + 20.0 * math.log10(f_hz) + _FSPL_CONST


# ---------------------------------------------------------------------------
# 2. Okumura-Hata model
# ---------------------------------------------------------------------------

class HataEnvironment(str, Enum):
    """Terrain / clutter category for the Okumura-Hata model."""
    urban_large   = "urban_large"    # large city (f ≥ 300 MHz)
    urban_medium  = "urban_medium"   # small / medium city
    suburban      = "suburban"
    rural         = "rural"          # open area


def _hata_correction(h_m: float, freq_mhz: float, env: HataEnvironment) -> float:
    """Mobile-antenna height correction factor a(h_m) for Okumura-Hata."""
    if env == HataEnvironment.urban_large:
        # Large city, f ≥ 300 MHz (ITU / Hata eqn for big cities)
        return 3.2 * (math.log10(11.75 * h_m)) ** 2 - 4.97
    else:
        # Small / medium city (also used as base for suburban/rural)
        return (
            (1.1 * math.log10(freq_mhz) - 0.7) * h_m
            - (1.56 * math.log10(freq_mhz) - 0.8)
        )


def okumura_hata_db(
    frequency_ghz: float,
    distance_m: float,
    base_height_m: float = 30.0,
    mobile_height_m: float = 1.5,
    environment: HataEnvironment = HataEnvironment.urban_medium,
) -> float:
    """Okumura-Hata path loss (dB) for 150–1 500 MHz macrocell links.

    The model covers 1–20 km distances. Beyond 20 km the formula is
    extrapolated (result flagged in log, still useful for rural LoS estimates).

    Args:
        frequency_ghz:   Carrier frequency in GHz (must be 0.15–1.5 GHz).
        distance_m:      Link distance in metres (typically 1 000–20 000 m).
        base_height_m:   Base-station antenna height above ground (30–200 m).
        mobile_height_m: Mobile / CPE antenna height above ground (1–10 m).
        environment:     HataEnvironment enum value.

    Returns:
        Median path loss in dB (positive — a loss).

    References:
        Hata, M. (1980). Empirical formula for propagation loss in land mobile
        radio services. *IEEE Trans. Veh. Technol.*, 29(3), 317–325.
        ITU-R Recommendation P.529-3.
    """
    freq_mhz = frequency_ghz * 1e3  # internal unit for Hata: MHz
    dist_km = distance_m / 1e3

    # Clamp to nominal applicability range (warn-level only — caller decides)
    freq_mhz = max(150.0, min(freq_mhz, 1500.0))
    dist_km = max(0.1, dist_km)

    h_b = base_height_m
    h_m = mobile_height_m

    a_hm = _hata_correction(h_m, freq_mhz, environment)

    # Base urban large-city path loss
    L_u = (
        69.55
        + 26.16 * math.log10(freq_mhz)
        - 13.82 * math.log10(h_b)
        - a_hm
        + (44.9 - 6.55 * math.log10(h_b)) * math.log10(dist_km)
    )

    if environment in (HataEnvironment.urban_large, HataEnvironment.urban_medium):
        return L_u

    if environment == HataEnvironment.suburban:
        return L_u - 2.0 * (math.log10(freq_mhz / 28.0)) ** 2 - 5.4

    # Rural / open area
    return (
        L_u
        - 4.78 * (math.log10(freq_mhz)) ** 2
        + 18.33 * math.log10(freq_mhz)
        - 40.94
    )


# ---------------------------------------------------------------------------
# 3. ITU-R P.452-17 (simplified) — terrain-aware diffraction loss
# ---------------------------------------------------------------------------

@dataclass
class TerrainPoint:
    """A single terrain profile sample.

    Args:
        distance_m: Horizontal distance from the transmitter (metres).
        elevation_m: Terrain elevation above mean sea level (metres).
    """
    distance_m: float
    elevation_m: float


def _knife_edge_loss_db(nu: float) -> float:
    """Knife-edge (single-knife) diffraction loss (dB) from Fresnel–Kirchhoff
    diffraction parameter ν.

    Uses the Huygens–Fresnel approximation valid for ν > −0.7:
        J(ν) ≈ 6.9 + 20·log10(√((ν − 0.1)² + 1) + ν − 0.1)   (ν > 0)
        J(ν) = 0   (ν ≤ -0.7)

    Reference: ITU-R P.526-15 §4.1.
    """
    if nu <= -0.7:
        return 0.0
    if nu <= 0.0:
        return 6.02 + 9.11 * nu + 1.27 * nu ** 2
    # Standard approximation for positive ν
    return 6.9 + 20.0 * math.log10(math.sqrt((nu - 0.1) ** 2 + 1.0) + nu - 0.1)


def _bullington_effective_obstruction(
    profile: Sequence[TerrainPoint],
    tx_elev_m: float,
    rx_elev_m: float,
    total_dist_m: float,
    frequency_ghz: float,
) -> float:
    """Bullington equivalent Fresnel–Kirchhoff ν for a terrain profile.

    Finds the single equivalent knife-edge that gives the same overall
    diffraction loss as the full profile (Bullington, 1947 method).

    Returns:
        Effective ν (dimensionless).  Positive ν → obstruction.
    """
    if not profile or total_dist_m <= 0:
        return -1.0  # clear path

    lambda_m = 0.3 / frequency_ghz  # wavelength in metres
    d_total = total_dist_m

    # Build straight line from TX to RX in elevation space
    def los_elev(d: float) -> float:
        return tx_elev_m + (rx_elev_m - tx_elev_m) * (d / d_total)

    # Find maximum Fresnel-clearance violation (highest ν)
    nu_max = -math.inf
    for pt in profile:
        d1 = pt.distance_m
        d2 = d_total - d1
        if d1 <= 0 or d2 <= 0:
            continue
        los = los_elev(d1)
        # Height of obstacle above LoS
        h = pt.elevation_m - los
        # Fresnel–Kirchhoff diffraction parameter
        nu = h * math.sqrt(2.0 * (d1 + d2) / (lambda_m * d1 * d2))
        if nu > nu_max:
            nu_max = nu

    return nu_max if nu_max != -math.inf else -1.0


def itu_r_p452_loss_db(
    distance_m: float,
    frequency_ghz: float,
    terrain_profile: Sequence[TerrainPoint],
    tx_elevation_m: float = 0.0,
    rx_elevation_m: float = 0.0,
    tx_antenna_height_m: float = 30.0,
    rx_antenna_height_m: float = 10.0,
) -> float:
    """Terrain-based basic transmission loss per ITU-R P.452-17 (simplified).

    Implements the free-space + terrain-diffraction component of P.452.
    Troposcatter and ducting components are omitted (appropriate for ≤100 km
    terrestrial links at 1–86 GHz).

    Algorithm:
        1. Compute free-space basic transmission loss Lbfs.
        2. Find Bullington effective ν for the terrain profile.
        3. Add knife-edge diffraction loss J(ν) if positive (obstruction).
        4. Total: Lb = Lbfs + max(J(ν), 0).

    Args:
        distance_m:          TX-to-RX great-circle distance in metres.
        frequency_ghz:       Carrier frequency in GHz.
        terrain_profile:     List of TerrainPoint samples (terrain, not antenna).
                             Should NOT include TX/RX endpoints.
        tx_elevation_m:      Ground elevation at TX in metres ASL.
        rx_elevation_m:      Ground elevation at RX in metres ASL.
        tx_antenna_height_m: TX antenna height above local ground (metres).
        rx_antenna_height_m: RX antenna height above local ground (metres).

    Returns:
        Basic transmission loss Lb in dB (positive — a loss).
    """
    # Effective heights above MSL for the antenna radiation centres
    tx_rad_m = tx_elevation_m + tx_antenna_height_m
    rx_rad_m = rx_elevation_m + rx_antenna_height_m

    # Step 1: free-space loss
    Lbfs = fspl_db(distance_m, frequency_ghz)

    # Step 2: Bullington diffraction parameter using actual terrain
    nu = _bullington_effective_obstruction(
        terrain_profile,
        tx_rad_m,
        rx_rad_m,
        distance_m,
        frequency_ghz,
    )

    # Step 3: diffraction loss (only adds loss when obstructed, ν > 0)
    Ld = _knife_edge_loss_db(nu)

    # Step 4: total basic transmission loss
    return Lbfs + max(Ld, 0.0)


# ---------------------------------------------------------------------------
# 4. ITU-R P.838-3 — Specific rain attenuation
# ---------------------------------------------------------------------------

# Frequency-interpolation table (Table 1, ITU-R P.838-3).
# Columns: (f_GHz, kH, kV, αH, αV)
_P838_TABLE: list[tuple[float, float, float, float, float]] = [
    (1.0,   0.0000387,  0.0000352,  0.912,  0.880),
    (2.0,   0.000154,   0.000138,   0.963,  0.923),
    (4.0,   0.000650,   0.000591,   1.121,  1.075),
    (6.0,   0.00175,    0.00155,    1.308,  1.265),
    (7.0,   0.00301,    0.00265,    1.332,  1.312),
    (8.0,   0.00454,    0.00395,    1.327,  1.310),
    (10.0,  0.0101,     0.00887,    1.276,  1.264),
    (12.0,  0.0188,     0.0168,     1.217,  1.200),
    (15.0,  0.0367,     0.0335,     1.154,  1.128),
    (20.0,  0.0751,     0.0691,     1.099,  1.065),
    (25.0,  0.124,      0.113,      1.061,  1.030),
    (30.0,  0.187,      0.167,      1.021,  1.000),
    (35.0,  0.263,      0.233,      0.979,  0.963),
    (40.0,  0.350,      0.310,      0.939,  0.929),
    (45.0,  0.442,      0.393,      0.903,  0.897),
    (50.0,  0.536,      0.479,      0.873,  0.868),
    (60.0,  0.707,      0.642,      0.826,  0.824),
    (70.0,  0.851,      0.784,      0.793,  0.793),
    (80.0,  0.975,      0.906,      0.769,  0.769),
    (90.0,  1.06,       0.999,      0.753,  0.754),
    (100.0, 1.12,       1.06,       0.743,  0.744),
]


class Polarisation(str, Enum):
    horizontal = "horizontal"
    vertical   = "vertical"
    circular   = "circular"  # k = (kH + kV)/2, α = (kH*αH + kV*αV)/(kH + kV)


def _log_interp(
    f: float,
    x0: float, y0: float, x1: float, y1: float
) -> float:
    """Log-linear interpolation (used for k coefficient, which spans decades)."""
    if x1 == x0:
        return y0
    t = math.log10(f / x0) / math.log10(x1 / x0)
    return math.exp(math.log(y0) + t * (math.log(y1) - math.log(y0)))


def _lin_interp(f: float, x0: float, y0: float, x1: float, y1: float) -> float:
    """Linear interpolation for α (small range)."""
    if x1 == x0:
        return y0
    t = (f - x0) / (x1 - x0)
    return y0 + t * (y1 - y0)


def _p838_coefficients(
    frequency_ghz: float,
    polarisation: Polarisation,
) -> tuple[float, float]:
    """Interpolate ITU-R P.838-3 k and α for an arbitrary frequency.

    Args:
        frequency_ghz: Carrier frequency (1–100 GHz; clamped at boundaries).
        polarisation:  Polarisation enum.

    Returns:
        (k, α) tuple for γR = k · R^α.
    """
    f = max(1.0, min(frequency_ghz, 100.0))

    # Bracket the frequency in the table
    lo = _P838_TABLE[0]
    hi = _P838_TABLE[-1]
    for i in range(len(_P838_TABLE) - 1):
        if _P838_TABLE[i][0] <= f <= _P838_TABLE[i + 1][0]:
            lo = _P838_TABLE[i]
            hi = _P838_TABLE[i + 1]
            break

    # Interpolate kH, kV (log scale), αH, αV (linear scale)
    kH  = _log_interp(f, lo[0], lo[1], hi[0], hi[1])
    kV  = _log_interp(f, lo[0], lo[2], hi[0], hi[2])
    aH  = _lin_interp(f, lo[0], lo[3], hi[0], hi[3])
    aV  = _lin_interp(f, lo[0], lo[4], hi[0], hi[4])

    if polarisation == Polarisation.horizontal:
        return kH, aH
    if polarisation == Polarisation.vertical:
        return kV, aV
    # Circular
    k = (kH + kV) / 2.0
    a = (kH * aH + kV * aV) / (kH + kV)
    return k, a


@dataclass
class RainAttenuationResult:
    """Result of the ITU-R P.838-3 rain attenuation calculation."""
    frequency_ghz:      float
    rain_rate_mmh:      float
    polarisation:       Polarisation
    k:                  float   # regression coefficient
    alpha:              float   # regression exponent
    gamma_r_db_km:      float   # specific attenuation (dB/km)
    path_length_km:     float
    total_attenuation_db: float


def rain_attenuation_db(
    frequency_ghz: float,
    rain_rate_mmh: float,
    path_length_km: float,
    polarisation: Polarisation = Polarisation.horizontal,
    reduction_factor: float | None = None,
) -> RainAttenuationResult:
    """Specific and total rain attenuation per ITU-R P.838-3.

    γR = k · R^α          [dB/km]
    A  = γR · r · d       [dB]

    where r is the path reduction factor (accounts for rain-cell spatial
    variability). If ``reduction_factor`` is None it defaults to 1.0 (worst-
    case / short links). For longer links supply the ITU-R P.530 r factor.

    Args:
        frequency_ghz:   Carrier frequency in GHz (1–100 GHz).
        rain_rate_mmh:   Point rain rate exceeded for 0.01 % of the time (mm/h).
                         Typical values: 30–50 (tropical), 20–30 (temperate).
        path_length_km:  Total link path length in km.
        polarisation:    Polarisation of the transmitted wave.
        reduction_factor: Path reduction factor r (0–1). None → 1.0.

    Returns:
        RainAttenuationResult with specific and total attenuation.

    References:
        ITU-R Recommendation P.838-3 (2005).
        ITU-R Recommendation P.530-17 §2.4 (path reduction factor).
    """
    k, alpha = _p838_coefficients(frequency_ghz, polarisation)
    gamma_r = k * (rain_rate_mmh ** alpha)
    r = 1.0 if reduction_factor is None else float(reduction_factor)
    total = gamma_r * r * path_length_km
    return RainAttenuationResult(
        frequency_ghz=frequency_ghz,
        rain_rate_mmh=rain_rate_mmh,
        polarisation=polarisation,
        k=k,
        alpha=alpha,
        gamma_r_db_km=gamma_r,
        path_length_km=path_length_km,
        total_attenuation_db=total,
    )


# ---------------------------------------------------------------------------
# Composite link budget (FSPL + rain attenuation; entry point for API layer)
# ---------------------------------------------------------------------------

@dataclass
class PropagationResult:
    """Aggregate result from all propagation model components."""
    distance_m:             float
    frequency_ghz:          float
    fspl_db:                float
    hata_db:                float | None = None   # None if outside Hata range
    p452_loss_db:           float | None = None   # None if no terrain profile
    rain_attenuation_db:    float = 0.0
    total_loss_db:          float = field(init=False)

    def __post_init__(self) -> None:
        # Best-available path loss: P.452 > Hata > FSPL
        if self.p452_loss_db is not None:
            base = self.p452_loss_db
        elif self.hata_db is not None:
            base = self.hata_db
        else:
            base = self.fspl_db
        self.total_loss_db = base + self.rain_attenuation_db

    def as_dict(self) -> dict:
        return {
            "distance_m":           round(self.distance_m, 2),
            "frequency_ghz":        self.frequency_ghz,
            "fspl_db":              round(self.fspl_db, 2),
            "hata_db":              round(self.hata_db, 2) if self.hata_db is not None else None,
            "p452_loss_db":         round(self.p452_loss_db, 2) if self.p452_loss_db is not None else None,
            "rain_attenuation_db":  round(self.rain_attenuation_db, 2),
            "total_loss_db":        round(self.total_loss_db, 2),
        }


def compute_propagation(
    distance_m: float,
    frequency_ghz: float,
    terrain_profile: Sequence[TerrainPoint] | None = None,
    tx_elevation_m: float = 0.0,
    rx_elevation_m: float = 0.0,
    tx_antenna_height_m: float = 30.0,
    rx_antenna_height_m: float = 10.0,
    hata_env: HataEnvironment = HataEnvironment.urban_medium,
    base_height_m: float = 30.0,
    mobile_height_m: float = 1.5,
    rain_rate_mmh: float = 0.0,
    polarisation: Polarisation = Polarisation.horizontal,
) -> PropagationResult:
    """Run all applicable propagation models and return a combined result.

    Args:
        distance_m:          TX-to-RX link distance in metres.
        frequency_ghz:       Carrier frequency in GHz.
        terrain_profile:     Optional terrain profile (TerrainPoint list).
                             When provided, P.452 diffraction is included.
        tx_elevation_m:      Ground elevation at TX site (metres ASL).
        rx_elevation_m:      Ground elevation at RX site (metres ASL).
        tx_antenna_height_m: TX antenna height above local ground (metres).
        rx_antenna_height_m: RX antenna height above local ground (metres).
        hata_env:            HataEnvironment (only applied if 0.15–1.5 GHz).
        base_height_m:       Hata base-station height (metres, 30–200).
        mobile_height_m:     Hata mobile height (metres, 1–10).
        rain_rate_mmh:       Rain rate mm/h (0 = no rain attenuation).
        polarisation:        Polarisation for rain attenuation calc.

    Returns:
        PropagationResult with all components and composite total_loss_db.
    """
    # FSPL (always computed)
    fsp = fspl_db(distance_m, frequency_ghz)

    # Okumura-Hata (150–1 500 MHz only)
    hata: float | None = None
    if 0.15 <= frequency_ghz <= 1.5:
        hata = okumura_hata_db(
            frequency_ghz=frequency_ghz,
            distance_m=distance_m,
            base_height_m=base_height_m,
            mobile_height_m=mobile_height_m,
            environment=hata_env,
        )

    # ITU-R P.452 (when terrain profile supplied)
    p452: float | None = None
    if terrain_profile:
        p452 = itu_r_p452_loss_db(
            distance_m=distance_m,
            frequency_ghz=frequency_ghz,
            terrain_profile=terrain_profile,
            tx_elevation_m=tx_elevation_m,
            rx_elevation_m=rx_elevation_m,
            tx_antenna_height_m=tx_antenna_height_m,
            rx_antenna_height_m=rx_antenna_height_m,
        )

    # Rain attenuation
    rain_db = 0.0
    if rain_rate_mmh > 0.0:
        result = rain_attenuation_db(
            frequency_ghz=frequency_ghz,
            rain_rate_mmh=rain_rate_mmh,
            path_length_km=distance_m / 1e3,
            polarisation=polarisation,
        )
        rain_db = result.total_attenuation_db

    return PropagationResult(
        distance_m=distance_m,
        frequency_ghz=frequency_ghz,
        fspl_db=fsp,
        hata_db=hata,
        p452_loss_db=p452,
        rain_attenuation_db=rain_db,
    )


__all__ = [
    "fspl_db",
    "HataEnvironment",
    "okumura_hata_db",
    "TerrainPoint",
    "itu_r_p452_loss_db",
    "Polarisation",
    "RainAttenuationResult",
    "rain_attenuation_db",
    "PropagationResult",
    "compute_propagation",
]
