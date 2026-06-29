"""WebSocket realtime topology stream tests.

Proves the event-driven ``/ws/topology`` rework: on connect a client gets a
``snapshot`` + ``wireless.plan``, and when a geo device is later placed via the
REST API every connected client receives the recomputed plan — the core of map
mode's live coverage/topology updates.

Uses the sync Starlette ``TestClient`` (its background event loop shares the
process-wide repo + event bus singletons with the request path).

Auth (RB-03): setiap WS connect memerlukan ``?token=<jwt>``; REST calls
menggunakan header Authorization.  Kedua-duanya digenerate oleh helper dari
conftest sehingga test tidak hardcode token.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import make_auth_headers, make_test_token


def test_topology_ws_sends_snapshot_and_live_plan():
    auth_headers = make_auth_headers()
    token = make_test_token()
    client = TestClient(app, headers=auth_headers)

    # seed a project to scope the socket to
    pid = client.post("/api/projects", json={"name": "ws-wisp", "description": ""}).json()["id"]

    with client.websocket_connect(f"/ws/topology?project={pid}&token={token}") as ws:
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
    auth_headers = make_auth_headers()
    token = make_test_token()
    client = TestClient(app, headers=auth_headers)

    pid = client.post("/api/projects", json={"name": "ws-ping", "description": ""}).json()["id"]
    with client.websocket_connect(f"/ws/topology?project={pid}&token={token}") as ws:
        ws.receive_json()  # snapshot
        ws.receive_json()  # wireless.plan
        ws.send_text("ping")
        # Heartbeat reply is a plain-text "pong" frame (frontend checks
        # ev.data === 'pong'; see frontend/src/api/ws.ts), not a JSON envelope.
        assert ws.receive_text() == "pong"
