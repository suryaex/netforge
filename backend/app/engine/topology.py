"""Network topology auto-generation for geo-placed devices.

When a device is placed on the NetForge map this module:

1. **Auto-connects** it to the nearest serving AP/tower within radio range,
   using the engine's full Friis link budget (not just distance).
2. **Calculates link budget** for every new association via
   ``engine.wireless.link_budget``.
3. **Assigns non-overlapping channels** to co-located APs using a greedy
   graph-colouring approach over the interference graph.

Design: pure and framework-agnostic (no FastAPI, no store imports).
The FastAPI layer at ``app/api/wireless.py`` or a future placement webhook
calls these functions after every node-placement event.

Channel planning
----------------
Standard non-overlapping 2.4 GHz channels: 1, 6, 11  (20 MHz)
Standard non-overlapping 5 GHz UNII channels (20 MHz): 36, 40, 44, 48,
  52, 56, 60, 64, 100, 104, 108, 112, 116, 120, 124, 128, 132, 136, 140,
  149, 153, 157, 161, 165
For 5 GHz 40/80 MHz the module uses the primary channel only for colouring.

Frequency-to-channel set map
-----------------------------
Devices are assigned channels from the pool that matches their configured
band (2.4 or 5 GHz).  The channel planner returns a ``ChannelAssignment``
per AP, with ``channel`` (integer) and ``frequency_ghz`` (float).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

from engine.wireless import (
    GeoDevice,
    LinkBudget,
    PlannedLink,
    Radio,
    haversine_m,
    link_budget,
    max_range_m,
)

# ---------------------------------------------------------------------------
# Constants — non-overlapping channel pools
# ---------------------------------------------------------------------------

_CHANNELS_24_GHZ: list[int] = [1, 6, 11]
_CHANNELS_5_GHZ: list[int] = [
    36, 40, 44, 48, 52, 56, 60, 64,
    100, 104, 108, 112, 116, 120, 124, 128, 132, 136, 140,
    149, 153, 157, 161, 165,
]

_CHANNEL_TO_FREQ: dict[int, float] = {
    # 2.4 GHz band
    1:   2.412, 2:  2.417, 3:  2.422, 4:  2.427, 5:  2.432,
    6:   2.437, 7:  2.442, 8:  2.447, 9:  2.452, 10: 2.457,
    11:  2.462, 12: 2.467, 13: 2.472, 14: 2.484,
    # 5 GHz UNII (primary 20 MHz channel centre, MHz → GHz)
    36:  5.180, 40:  5.200, 44:  5.220, 48:  5.240,
    52:  5.260, 56:  5.280, 60:  5.300, 64:  5.320,
    100: 5.500, 104: 5.520, 108: 5.540, 112: 5.560,
    116: 5.580, 120: 5.600, 124: 5.620, 128: 5.640,
    132: 5.660, 136: 5.680, 140: 5.700,
    149: 5.745, 153: 5.765, 157: 5.785, 161: 5.805, 165: 5.825,
}

SERVING_ROLES = frozenset({"ap", "tower"})


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class AutoLink:
    """A single auto-generated wireless association."""
    device_id:    str    # the newly placed (or re-evaluated) device
    parent_id:    str    # serving AP / tower
    budget:       LinkBudget
    distance_m:   float

    def as_dict(self) -> dict:
        return {
            "device_id": self.device_id,
            "parent_id": self.parent_id,
            "distance_m": round(self.distance_m, 1),
            **self.budget.as_dict(),
        }


@dataclass
class ChannelAssignment:
    """Channel plan result for a single serving device."""
    device_id:     str
    channel:       int
    frequency_ghz: float
    band:          str   # "2.4GHz" | "5GHz"

    def as_dict(self) -> dict:
        return {
            "device_id":     self.device_id,
            "channel":       self.channel,
            "frequency_ghz": self.frequency_ghz,
            "band":          self.band,
        }


@dataclass
class TopologyPlan:
    """Combined result of auto-connect + channel-plan for a device set."""
    links:    list[AutoLink]           = field(default_factory=list)
    channels: list[ChannelAssignment]  = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "links":    [l.as_dict() for l in self.links],
            "channels": [c.as_dict() for c in self.channels],
        }


# ---------------------------------------------------------------------------
# Auto-connect: best-parent selection
# ---------------------------------------------------------------------------

def auto_connect(
    new_device: GeoDevice,
    existing_devices: Sequence[GeoDevice],
) -> AutoLink | None:
    """Connect ``new_device`` to the nearest feasible serving AP/tower.

    Selection criteria (in priority order):
      1. Link must be feasible (RSSI ≥ rx_sensitivity).
      2. Prefer the parent with the highest RSSI (strongest signal).
      3. Ties broken by shortest distance, then parent ID (deterministic).

    Args:
        new_device:       The device being placed on the map.
        existing_devices: All devices already on the map (including APs).

    Returns:
        An :class:`AutoLink` for the best parent, or ``None`` if no feasible
        parent exists within radio range.
    """
    best: AutoLink | None = None

    for srv in existing_devices:
        if srv.id == new_device.id:
            continue
        if srv.role not in SERVING_ROLES:
            continue

        dist = haversine_m(new_device.lat, new_device.lon, srv.lat, srv.lon)

        # Quick range pre-filter (avoids expensive budget for distant APs)
        ap_range = max_range_m(srv.radio, new_device.radio)
        if dist > ap_range * 1.05:  # 5 % tolerance
            continue

        budget = link_budget(srv.radio, new_device.radio, dist)
        if not budget.feasible:
            continue

        candidate = AutoLink(
            device_id=new_device.id,
            parent_id=srv.id,
            budget=budget,
            distance_m=dist,
        )

        if best is None or _auto_link_better(candidate, best):
            best = candidate

    return best


def _auto_link_better(a: AutoLink, b: AutoLink) -> bool:
    """Return True if ``a`` is a better parent than ``b``."""
    if a.budget.rssi_dbm != b.budget.rssi_dbm:
        return a.budget.rssi_dbm > b.budget.rssi_dbm
    if a.distance_m != b.distance_m:
        return a.distance_m < b.distance_m
    return a.parent_id < b.parent_id


def auto_connect_all(
    devices: Sequence[GeoDevice],
) -> list[AutoLink]:
    """Connect every non-serving device to its best parent.

    Each non-AP/tower device is independently evaluated.  The result is
    equivalent to running :func:`auto_connect` for each client against the
    full serving set.

    Serving-to-serving backhaul links (tower ↔ AP) are also included:
    each AP is connected to its best serving tower if one is reachable.

    Args:
        devices: All geo-placed devices in the project.

    Returns:
        Sorted list of :class:`AutoLink` objects (client links first, then
        backhaul), deterministic ordering.
    """
    serving = [d for d in devices if d.role in SERVING_ROLES]
    seen: set[frozenset[str]] = set()
    links: list[AutoLink] = []

    for dev in devices:
        # Clients connect to APs; APs may connect upward to towers
        if dev.role in SERVING_ROLES:
            # APs look for tower parents (backhaul)
            candidates = [s for s in serving if s.role == "tower" and s.id != dev.id]
        else:
            candidates = serving

        if not candidates:
            continue

        link = auto_connect(dev, candidates)
        if link is None:
            continue

        pair = frozenset({link.device_id, link.parent_id})
        if pair in seen:
            continue
        seen.add(pair)
        links.append(link)

    links.sort(key=lambda l: (l.parent_id, l.device_id))
    return links


# ---------------------------------------------------------------------------
# Channel planning — greedy graph colouring
# ---------------------------------------------------------------------------

def _band_for(radio: Radio) -> str:
    return "2.4GHz" if radio.frequency_ghz < 3.0 else "5GHz"


def _channel_pool(radio: Radio) -> list[int]:
    return _CHANNELS_24_GHZ if radio.frequency_ghz < 3.0 else _CHANNELS_5_GHZ


def _aps_interfere(a: GeoDevice, b: GeoDevice) -> bool:
    """Two APs interfere if a CPE could plausibly associate with both.

    Heuristic: APs interfere if the distance between them is less than the
    sum of their individual coverage radii.  This is conservative — real
    co-channel interference depends on path loss to shared clients.
    """
    dist = haversine_m(a.lat, a.lon, b.lat, b.lon)
    r_a = max_range_m(a.radio, a.radio)
    r_b = max_range_m(b.radio, b.radio)
    return dist < (r_a + r_b)


def plan_channels(
    devices: Sequence[GeoDevice],
) -> list[ChannelAssignment]:
    """Assign non-overlapping channels to all serving APs/towers.

    Uses greedy graph colouring on the interference graph:
      - Nodes = serving APs/towers
      - Edges = pairs that interfere (overlapping coverage areas)
      - Colours = non-overlapping channel numbers for the device's band

    APs with the most neighbours are coloured first (saturation ordering)
    to minimise channel reuse.

    Args:
        devices: All geo-placed devices in the project.

    Returns:
        List of :class:`ChannelAssignment` objects, one per serving device.
    """
    serving = [d for d in devices if d.role in SERVING_ROLES]
    if not serving:
        return []

    # Build interference graph
    neighbours: dict[str, list[str]] = {s.id: [] for s in serving}
    for i, a in enumerate(serving):
        for b in serving[i + 1:]:
            if _aps_interfere(a, b):
                neighbours[a.id].append(b.id)
                neighbours[b.id].append(a.id)

    # Sort by descending neighbour count (saturation-first)
    order = sorted(serving, key=lambda d: -len(neighbours[d.id]))

    assigned: dict[str, int] = {}   # device_id -> channel number

    for dev in order:
        pool = _channel_pool(dev.radio)
        used_by_neighbours = {
            assigned[nb] for nb in neighbours[dev.id] if nb in assigned
        }
        # Pick the lowest-numbered channel not used by any neighbour
        chosen: int | None = None
        for ch in pool:
            if ch not in used_by_neighbours:
                chosen = ch
                break
        if chosen is None:
            # All channels exhausted — reuse the least-common one
            from collections import Counter
            counts = Counter(assigned[nb] for nb in neighbours[dev.id] if nb in assigned)
            chosen = min(pool, key=lambda c: counts.get(c, 0))
        assigned[dev.id] = chosen

    result: list[ChannelAssignment] = []
    for dev in serving:
        ch = assigned.get(dev.id, _channel_pool(dev.radio)[0])
        freq = _CHANNEL_TO_FREQ.get(ch, dev.radio.frequency_ghz)
        result.append(ChannelAssignment(
            device_id=dev.id,
            channel=ch,
            frequency_ghz=freq,
            band=_band_for(dev.radio),
        ))

    result.sort(key=lambda c: c.device_id)
    return result


# ---------------------------------------------------------------------------
# Combined entry point
# ---------------------------------------------------------------------------

def plan_topology(devices: Sequence[GeoDevice]) -> TopologyPlan:
    """Run auto-connect + channel planning for a full device set.

    Args:
        devices: All geo-placed devices (serving + client).

    Returns:
        :class:`TopologyPlan` with ``links`` and ``channels`` lists.
    """
    return TopologyPlan(
        links=auto_connect_all(devices),
        channels=plan_channels(devices),
    )


__all__ = [
    "AutoLink",
    "ChannelAssignment",
    "TopologyPlan",
    "auto_connect",
    "auto_connect_all",
    "plan_channels",
    "plan_topology",
]
