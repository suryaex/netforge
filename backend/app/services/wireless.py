"""Wireless planning service — adapts stored geo nodes to the RF engine.

Pulls nodes that carry a geographic position (``lat``/``lon``) from a project,
maps each to an ``engine.wireless.GeoDevice``, and runs the deterministic
planner / link-budget primitives. Like ``services/sim.py`` this is the seam
between the persistence schema (``app.models``) and the engine's own shapes.

Unit conventions: the schema's :class:`Radio` and the engine's ``Radio`` use the
*same* units (dBm / GHz / dBi / MHz / metres), so the mapping is field-for-field
with no conversion.
"""
from __future__ import annotations

from app.models import (
    CoverageCircle,
    Node,
    Radio,
    Topology,
    WirelessLink,
    WirelessPlanResult,
)
from engine import wireless as rf

# How a stored NodeKind maps onto an engine planner "role".
_ROLE_BY_KIND = {
    "ap": "ap",
    "olt": "tower",
    "host": "cpe",
    "server": "cpe",
    "router": "router",
    "switch": "switch",
    "firewall": "router",
}


def _to_engine_radio(r: Radio | None) -> rf.Radio:
    if r is None:
        return rf.Radio()
    return rf.Radio(
        tx_power_dbm=r.tx_power_dbm,
        frequency_ghz=r.frequency_ghz,
        antenna_gain_dbi=r.antenna_gain_dbi,
        bandwidth_mhz=r.bandwidth_mhz,
        rx_sensitivity_dbm=r.rx_sensitivity_dbm,
        misc_loss_db=r.misc_loss_db,
        max_range_m=r.max_range_m,
    )


def _role_for(node: Node) -> str:
    kind = str(node.kind)
    # A node placed on a tower position is modelled by kind=ap with a tower
    # intent flag; default to the kind→role table otherwise.
    if node.intent and node.intent.get("map_role") == "tower":
        return "tower"
    return _ROLE_BY_KIND.get(kind, "cpe")


def _geo_devices(nodes: list[Node]) -> list[rf.GeoDevice]:
    out: list[rf.GeoDevice] = []
    for n in nodes:
        if n.lat is None or n.lon is None:
            continue
        out.append(
            rf.GeoDevice(
                id=n.id,
                role=_role_for(n),
                lat=n.lat,
                lon=n.lon,
                radio=_to_engine_radio(n.radio),
            )
        )
    return out


def plan_topology(topo: Topology) -> WirelessPlanResult:
    """Run the RF planner over a project's geo-placed nodes.

    Returns the planned wireless links (with full link budgets) plus a coverage
    circle per serving node, ready for the map to render."""
    geo = _geo_devices(topo.nodes)
    by_id = {g.id: g for g in geo}

    planned = rf.plan_links(geo)
    links = [
        WirelessLink(
            a_id=p.a_id,
            b_id=p.b_id,
            distance_m=round(p.budget.distance_m, 2),
            fspl_db=round(p.budget.fspl_db, 2),
            rssi_dbm=round(p.budget.rssi_dbm, 2),
            margin_db=round(p.budget.margin_db, 2),
            noise_floor_dbm=round(p.budget.noise_floor_dbm, 2),
            snr_db=round(p.budget.snr_db, 2),
            quality=p.budget.quality.value,
            feasible=p.budget.feasible,
        )
        for p in planned
    ]

    coverage: list[CoverageCircle] = []
    for g in geo:
        if g.role in ("ap", "tower"):
            radius = rf.max_range_m(g.radio, g.radio)
            coverage.append(
                CoverageCircle(node_id=g.id, lat=g.lat, lon=g.lon, radius_m=round(radius, 1))
            )

    _ = by_id  # reserved for future per-link enrichment
    return WirelessPlanResult(project_id=topo.project.id, links=links, coverage=coverage)


def coverage_radius(node: Node) -> float:
    """Theoretical coverage radius (m) of a single serving node."""
    radio = _to_engine_radio(node.radio)
    return round(rf.max_range_m(radio, radio), 1)


def link_budget_between(
    tx: Radio,
    rx: Radio | None,
    *,
    distance_m: float | None = None,
    a_lat: float | None = None,
    a_lon: float | None = None,
    b_lat: float | None = None,
    b_lon: float | None = None,
    rain_rate_mm_hr: float = 0.0,
) -> rf.LinkBudget:
    """Compute a single point-to-point budget. Distance is taken from
    ``distance_m`` if given, else derived from the two coordinate pairs."""
    etx = _to_engine_radio(tx)
    erx = _to_engine_radio(rx) if rx is not None else etx
    if distance_m is None:
        if None in (a_lat, a_lon, b_lat, b_lon):
            raise ValueError("provide distance_m or both endpoint coordinates")
        distance_m = rf.haversine_m(a_lat, a_lon, b_lat, b_lon)  # type: ignore[arg-type]
    return rf.link_budget(etx, erx, distance_m, rain_rate_mm_hr)


__all__ = ["plan_topology", "coverage_radius", "link_budget_between"]
