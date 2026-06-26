"""WebSocket realtime topology stream tests.

Proves the event-driven ``/ws/topology`` rework: on connect a client gets a
``snapshot`` + ``wireless.plan``, and when a geo device is later placed via the
REST API every connected client receives the recomputed plan — the core of map
mode's live coverage/topology updates.

Uses the sync Starlette ``TestClient`` (its background event loop shares the
process-wide repo + event bus singletons with the request path).
"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.main import app


def test_topology_ws_sends_snapshot_and_live_plan():
    client = TestClient(app)
    # seed a project to scope the socket to
    pid = client.post("/api/projects", json={"name": "ws-wisp", "description": ""}).json()["id"]

    with client.websocket_connect(f"/ws/topology?project={pid}") as ws:
        first = ws.receive_json()
        assert first["type"] == "snapshot"
        assert first["topology"]["project"]["id"] == pid

        second = ws.receive_json()
        assert second["type"] == "wireless.plan"
        assert second["project_id"] == pid

        # place an AP via REST → expect node.updated + wireless.plan deltas
        client.post("/api/nodes", json={
            "project_id": pid, "name": "AP-1", "kind": "ap", "nos": "forgeos",
            "lat": -6.2, "lon": 106.8,
            "radio": {"tx_power_dbm": 23, "frequency_ghz": 5.8, "antenna_gain_dbi": 16},
        })

        types = set()
        for _ in range(2):
            ev = ws.receive_json()
            types.add(ev["type"])
        assert "node.updated" in types
        assert "wireless.plan" in types


def test_topology_ws_ping_pong():
    client = TestClient(app)
    pid = client.post("/api/projects", json={"name": "ws-ping", "description": ""}).json()["id"]
    with client.websocket_connect(f"/ws/topology?project={pid}") as ws:
        ws.receive_json()  # snapshot
        ws.receive_json()  # wireless.plan
        ws.send_text("ping")
        assert ws.receive_json() == {"type": "pong"}
