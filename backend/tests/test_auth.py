"""JWT authentication tests — covers RB-01, RB-03, and RB-07 from
docs/security/REMEDIATION_BACKLOG.md.

Test matrix:
  * Login success → 200 + valid JWT
  * Bad password → 401 UNAUTHORIZED
  * Unknown user → 401 UNAUTHORIZED (same response to prevent enumeration)
  * Missing token on protected route → 401
  * Malformed / expired token on protected route → 401
  * Valid token passes protected route → 200
  * GET /auth/me requires token
  * GET /auth/me returns correct identity with valid token
  * WS /ws/topology rejects connection without token
  * WS /ws/topology accepts connection with valid token + responds to ping

Fixtures (autouse from conftest): ``_seed_admin`` seeds the test admin user
before each test; ``_reset_repo`` clears the in-memory store.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.config import get_settings
from app.core.security import create_access_token
from app.main import app

# ---- Fixtures ---------------------------------------------------------------

_TEST_USER = "testadmin"
_TEST_PASS = "TestPass123!"

# Note: conftest._seed_admin autouse fixture seeds _TEST_USER before each test.


@pytest_asyncio.fixture
async def anon():
    """Unauthenticated async client — no Authorization header (for 401 scenario tests)."""
    from httpx import ASGITransport, AsyncClient
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---- Login endpoint ---------------------------------------------------------

async def test_login_success(anon):
    """Valid credentials → 200 with access_token."""
    resp = await anon.post("/api/auth/login", json={"username": _TEST_USER, "password": _TEST_PASS})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert isinstance(data["expires_in"], int) and data["expires_in"] > 0


async def test_login_bad_password(anon):
    """Wrong password → 401 with standard error envelope."""
    resp = await anon.post("/api/auth/login", json={"username": _TEST_USER, "password": "wrong!"})
    assert resp.status_code == 401, resp.text
    body = resp.json()
    assert body["success"] is False
    assert body["error"]["code"] == "UNAUTHORIZED"
    # Response must never hint at whether the username or password was wrong.
    assert "Invalid username or password" in body["error"]["message"]


async def test_login_unknown_user(anon):
    """Unknown username → same 401 shape (prevents username enumeration)."""
    resp = await anon.post("/api/auth/login", json={"username": "ghost", "password": "anything"})
    assert resp.status_code == 401
    body = resp.json()
    assert body["success"] is False
    assert body["error"]["code"] == "UNAUTHORIZED"


# ---- Protected route — missing or invalid token ----------------------------

async def test_protected_route_no_token(anon):
    """No Authorization header → 401."""
    resp = await anon.get("/api/projects")
    assert resp.status_code == 401


async def test_protected_route_malformed_token(anon):
    """Garbage bearer token → 401."""
    resp = await anon.get("/api/projects", headers={"Authorization": "Bearer notavalidjwt"})
    assert resp.status_code == 401


async def test_protected_route_wrong_scheme(anon):
    """Basic auth instead of Bearer → 401."""
    resp = await anon.get("/api/projects", headers={"Authorization": "Basic dXNlcjpwYXNz"})
    assert resp.status_code == 401


async def test_protected_route_expired_token(anon):
    """Token with exp in the past → 401."""
    settings = get_settings()
    expired_token = create_access_token(
        sub=_TEST_USER, role="admin",
        secret=settings.SECRET_KEY,
        expires_in=-1,  # already expired
    )
    resp = await anon.get(
        "/api/projects",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert resp.status_code == 401


# ---- Protected route — valid token -----------------------------------------

async def test_protected_route_valid_token(anon):
    """Valid JWT → 200 from a protected endpoint."""
    # First get a token via login.
    login_resp = await anon.post(
        "/api/auth/login",
        json={"username": _TEST_USER, "password": _TEST_PASS},
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]

    resp = await anon.get(
        "/api/projects",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200


# ---- /auth/me ---------------------------------------------------------------

async def test_auth_me_no_token(anon):
    """/auth/me without a token → 401."""
    resp = await anon.get("/api/auth/me")
    assert resp.status_code == 401


async def test_auth_me_with_valid_token(anon):
    """/auth/me with a valid token → 200 + identity."""
    login_resp = await anon.post(
        "/api/auth/login",
        json={"username": _TEST_USER, "password": _TEST_PASS},
    )
    token = login_resp.json()["access_token"]
    resp = await anon.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == _TEST_USER
    assert data["role"] == "admin"


# ---- Public endpoints stay public ------------------------------------------

async def test_health_is_public(anon):
    """GET /api/health requires no token."""
    resp = await anon.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ---- WebSocket auth (RB-03) — sync TestClient ------------------------------

def test_ws_topology_rejects_missing_token():
    """WS connect without ?token → connection closed (4401 or generic error)."""
    client = TestClient(app, raise_server_exceptions=False)
    with pytest.raises((WebSocketDisconnect, Exception)):
        with client.websocket_connect("/ws/topology") as ws:
            # If we ever get data after connecting, we fail the test.
            ws.receive_text()


def test_ws_topology_rejects_invalid_token():
    """WS connect with garbage token → connection closed."""
    client = TestClient(app, raise_server_exceptions=False)
    with pytest.raises((WebSocketDisconnect, Exception)):
        with client.websocket_connect("/ws/topology?token=notvalid") as ws:
            ws.receive_text()


def test_ws_topology_accepts_valid_token():
    """WS connect with valid JWT token → accepted + ping/pong works."""
    settings = get_settings()
    token = create_access_token(
        sub=_TEST_USER, role="admin",
        secret=settings.SECRET_KEY,
        expires_in=3600,
    )
    auth_headers = {"Authorization": f"Bearer {token}"}
    client = TestClient(app, headers=auth_headers)

    # Create a project (requires auth on the REST side too)
    pid = client.post(
        "/api/projects", json={"name": "auth-ws-test", "description": ""}
    ).json()["id"]

    with client.websocket_connect(f"/ws/topology?project={pid}&token={token}") as ws:
        first = ws.receive_json()
        assert first["type"] == "snapshot"
        ws.receive_json()   # wireless.plan
        ws.send_text("ping")
        assert ws.receive_text() == "pong"


def test_ws_console_rejects_missing_token():
    """WS console without ?token → connection closed."""
    client = TestClient(app, raise_server_exceptions=False)
    with pytest.raises((WebSocketDisconnect, Exception)):
        with client.websocket_connect("/ws/console/fake-node-id") as ws:
            ws.receive_text()
