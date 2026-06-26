"""Tests for the geo-aware wireless engine + API.

Covers the pure RF physics (FSPL, Friis link budget, coverage radius, Fresnel,
LoS, ITU-R P.838 rain fade, deterministic planner) and the HTTP surface
(``/api/wireless/*``). Network-dependent paths (elevation provider) are exercised
only via the offline ``profile`` input so the suite stays deterministic.
"""
from __future__ import annotations

import math

import pytest

from engine import wireless as rf


# --- pure physics -----------------------------------------------------------
def test_fspl_matches_friis_reference():
    # 1 km @ 5.8 GHz free space ≈ 107.7 dB
    loss = rf.fspl_db(1000.0, 5.8e9)
    assert 107.0 < loss < 108.5


def test_fspl_clamped_at_one_metre():
    # No blow-up / negative-infinity for co-located points.
    assert rf.fspl_db(0.0, 5.8e9) == rf.fspl_db(1.0, 5.8e9)


def test_link_budget_strong_when_close():
    tx = rf.Radio(tx_power_dbm=20, frequency_ghz=5.8, antenna_gain_dbi=14)
    b = rf.link_budget(tx, tx, 50.0)
    assert b.feasible
    assert b.quality in (rf.LinkQuality.excellent, rf.LinkQuality.good)
    assert b.rssi_dbm > tx.rx_sensitivity_dbm


def test_link_budget_unusable_when_far():
    tx = rf.Radio(tx_power_dbm=20, frequency_ghz=5.8, rx_sensitivity_dbm=-85)
    b = rf.link_budget(tx, tx, 500_000.0)  # 500 km — way past budget
    assert not b.feasible
    assert b.quality is rf.LinkQuality.unusable


def test_max_range_is_self_consistent():
    # RSSI at the computed max range should sit right at sensitivity.
    radio = rf.Radio()
    d = rf.max_range_m(radio, radio)
    rssi = rf.rx_power_dbm(radio, radio, d)
    assert math.isclose(rssi, radio.rx_sensitivity_dbm, abs_tol=0.5)


def test_haversine_known_distance():
    # ~1 deg of latitude ≈ 111 km
    d = rf.haversine_m(0.0, 0.0, 1.0, 0.0)
    assert 110_000 < d < 112_000


def test_rain_fade_increases_with_frequency():
    # At 60 GHz rain bites far harder than at 5.8 GHz for the same rate.
    low = rf.rain_specific_attenuation_db_km(5.8, 50.0)
    high = rf.rain_specific_attenuation_db_km(60.0, 50.0)
    assert high > low > 0


def test_rain_fade_reduces_rssi():
    tx = rf.Radio(frequency_ghz=28.0)
    clear = rf.link_budget(tx, tx, 2000.0, rain_rate_mm_hr=0.0)
    wet = rf.link_budget(tx, tx, 2000.0, rain_rate_mm_hr=50.0)
    assert wet.rssi_dbm < clear.rssi_dbm


def test_fresnel_radius_peaks_at_midpoint():
    mid = rf.fresnel_radius_m(500, 500, 5.8e9)
    edge = rf.fresnel_radius_m(100, 900, 5.8e9)
    assert mid > edge > 0
    assert rf.fresnel_radius_m(0, 1000, 5.8e9) == 0.0


def test_line_of_sight_clear_path():
    # Flat ground, both antennas elevated → clear LoS and Fresnel.
    profile = [(i * 100.0, 0.0) for i in range(11)]  # 1 km, flat at 0 m
    res = rf.line_of_sight(1000.0, 5.8e9, tx_height_m=30, rx_height_m=30, profile=profile)
    assert res.los_clear
    assert res.fresnel_clear


def test_line_of_sight_blocked_by_hill():
    # A 60 m hill in the middle of a 1 km path with 10 m antennas blocks LoS.
    profile = [(i * 100.0, 0.0) for i in range(11)]
    profile[5] = (500.0, 60.0)
    res = rf.line_of_sight(1000.0, 5.8e9, tx_height_m=10, rx_height_m=10, profile=profile)
    assert not res.los_clear
    assert res.worst_obstruction_m > 0


def test_planner_is_deterministic_and_associates_cpe():
    ap = rf.GeoDevice("ap1", "ap", 0.0, 0.0, rf.Radio())
    cpe = rf.GeoDevice("cpe1", "cpe", 0.001, 0.001, rf.Radio())  # ~157 m away
    plan1 = rf.plan_links([ap, cpe])
    plan2 = rf.plan_links([cpe, ap])  # different input order
    assert [p.as_dict() for p in plan1] == [p.as_dict() for p in plan2]
    assert len(plan1) == 1
    assert plan1[0].a_id == "ap1" and plan1[0].b_id == "cpe1"


# --- HTTP surface -----------------------------------------------------------
async def test_link_budget_endpoint(client):
    resp = await client.post(
        "/api/wireless/link-budget",
        json={
            "tx": {"tx_power_dbm": 23, "frequency_ghz": 5.8, "antenna_gain_dbi": 16},
            "distance_m": 800,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["feasible"] is True
    assert body["quality"] in ("excellent", "good", "fair", "weak")


async def test_link_budget_endpoint_requires_distance_or_coords(client):
    resp = await client.post(
        "/api/wireless/link-budget",
        json={"tx": {"tx_power_dbm": 20, "frequency_ghz": 5.8}},
    )
    assert resp.status_code == 422


async def test_los_check_with_offline_profile(client):
    profile = [{"lat": 0.0, "lon": 0.0, "elevation_m": 0.0, "distance_m": d * 100.0}
               for d in range(11)]
    resp = await client.post(
        "/api/wireless/los-check",
        json={
            "a_lat": 0.0, "a_lon": 0.0, "b_lat": 0.0, "b_lon": 0.009,
            "frequency_ghz": 5.8, "tx_height_m": 30, "rx_height_m": 30,
            "profile": profile,
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["los_clear"] is True


async def test_wireless_plan_endpoint(client):
    pr = await client.post("/api/projects", json={"name": "wisp", "description": ""})
    pid = pr.json()["id"]

    await client.post("/api/nodes", json={
        "project_id": pid, "name": "AP-1", "kind": "ap", "nos": "forgeos",
        "lat": -6.20, "lon": 106.80,
        "radio": {"tx_power_dbm": 23, "frequency_ghz": 5.8, "antenna_gain_dbi": 16},
    })
    await client.post("/api/nodes", json={
        "project_id": pid, "name": "CPE-1", "kind": "host", "nos": "forgeos",
        "lat": -6.2008, "lon": 106.8008,
        "radio": {"tx_power_dbm": 20, "frequency_ghz": 5.8, "antenna_gain_dbi": 12},
    })

    resp = await client.get(f"/api/wireless/plan/{pid}")
    assert resp.status_code == 200, resp.text
    plan = resp.json()
    assert plan["project_id"] == pid
    assert len(plan["coverage"]) == 1          # one AP radiates a coverage circle
    assert len(plan["links"]) == 1             # CPE associates to the AP
    assert plan["links"][0]["feasible"] is True


async def test_geo_fields_round_trip_on_node(client):
    pr = await client.post("/api/projects", json={"name": "geo", "description": ""})
    pid = pr.json()["id"]
    resp = await client.post("/api/nodes", json={
        "project_id": pid, "name": "AP", "kind": "ap", "nos": "forgeos",
        "lat": 1.23, "lon": 4.56,
        "radio": {"tx_power_dbm": 20, "frequency_ghz": 5.0},
    })
    assert resp.status_code == 201, resp.text
    node = resp.json()
    assert node["lat"] == 1.23 and node["lon"] == 4.56
    assert node["radio"]["frequency_ghz"] == 5.0
