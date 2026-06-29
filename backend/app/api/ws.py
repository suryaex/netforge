"""WebSocket endpoints: live topology/telemetry and per-node console.

For v0.1 these are in-process broadcasters. Production fans out via Redis
pub/sub (infra/redis-design.md) so multiple API workers share one event bus.

Auth (RB-03):
  Token validation happens BEFORE ``ws.accept()``.  The JWT is supplied as the
  ``?token=<jwt>`` query parameter — browsers cannot send the Authorization
  header in the WebSocket upgrade handshake.  An invalid or missing token causes
  the handler to close the connection with code 4401 without ever accepting it.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.api.deps import get_current_user_ws
from app.services.events import get_bus
from app.services import wireless as wsvc
from app.store import get_repo
from app.store import NotFound

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _reject_ws(ws: WebSocket, code: int, reason: str) -> None:
    """Close a WebSocket before or after accept, swallowing transport errors."""
    with contextlib.suppress(Exception):
        await ws.close(code=code, reason=reason)


# ---------------------------------------------------------------------------
# /ws/topology
# ---------------------------------------------------------------------------

@router.websocket("/ws/topology")
async def ws_topology(
    ws: WebSocket,
    project: str | None = Query(default=None),
    token: str | None = Query(default=None),
):
    """Event-driven topology stream.

    Authentication: ``?token=<jwt>`` query parameter required.

    On connect we push a full ``snapshot`` (plus the current ``wireless.plan``
    when a project is scoped), then relay deltas published on the in-process bus
    by mutating endpoints — so the moment a device is placed/moved on the map,
    every open client sees the recomputed links and RSSI without polling.

    A client may scope the stream with ``?project=<id>``; otherwise it receives
    global events. ``ping`` text frames are answered with ``pong`` for heartbeat.
    """
    # --- RB-03: validate token BEFORE accepting the connection ---------------
    if not token:
        await _reject_ws(ws, code=4401, reason="Unauthorized: missing token")
        return
    try:
        _user = await get_current_user_ws(token)
    except ValueError as exc:
        logger.debug("WS topology auth failed: %s", exc)
        await _reject_ws(ws, code=4401, reason="Unauthorized: invalid token")
        return

    await ws.accept()
    repo = get_repo()
    bus = get_bus()

    # --- initial snapshot ---------------------------------------------------
    if project:
        try:
            topo = await repo.topology(project)
            await ws.send_json(
                {"type": "snapshot", "topology": topo.model_dump(mode="json")}
            )
            plan = wsvc.plan_topology(topo)
            await ws.send_json({"type": "wireless.plan", **plan.model_dump(mode="json")})
        except NotFound:
            with contextlib.suppress(Exception):
                await ws.send_json({"type": "error", "reason": "project not found"})
        except WebSocketDisconnect:
            return

    # --- fan-out loop -------------------------------------------------------
    async def pump_client() -> None:
        """Relay client → server frames (ping/pong). Raises on disconnect."""
        while True:
            msg = await ws.receive_text()
            if msg == "ping":
                # Send plain-text "pong" so the frontend's ev.data === 'pong' check works.
                await ws.send_text("pong")

    async with bus.subscription(project) as events:

        async def pump_bus() -> None:
            async for event in events:
                await ws.send_json(event)

        client_task = asyncio.create_task(pump_client())
        bus_task = asyncio.create_task(pump_bus())
        # asyncio.wait() does NOT propagate task exceptions — each task's
        # exception is stored on the task object.  Disconnect is handled
        # implicitly: pump_client raises WebSocketDisconnect inside its task,
        # FIRST_COMPLETED fires, and the finally block cancels both tasks.
        try:
            await asyncio.wait(
                {client_task, bus_task}, return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            for t in (client_task, bus_task):
                t.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await t


# ---------------------------------------------------------------------------
# /ws/console/{node_id}
# ---------------------------------------------------------------------------

@router.websocket("/ws/console/{node_id}")
async def ws_console(
    ws: WebSocket,
    node_id: str,
    token: str | None = Query(default=None),
):
    """A simulated device console. Echoes a banner then relays line input to a
    (stub) command handler. Real emul-mode attaches this to the container PTY.

    Authentication: ``?token=<jwt>`` query parameter required.
    The node_id path param is validated against the repo after auth so that
    unauthorized callers cannot probe whether a node ID exists.
    """
    # --- RB-03: validate token BEFORE accepting the connection ---------------
    if not token:
        await _reject_ws(ws, code=4401, reason="Unauthorized: missing token")
        return
    try:
        _user = await get_current_user_ws(token)
    except ValueError as exc:
        logger.debug("WS console auth failed for node=%r: %s", node_id, exc)
        await _reject_ws(ws, code=4401, reason="Unauthorized: invalid token")
        return

    await ws.accept()
    repo = get_repo()
    try:
        node = await repo.get_node(node_id)
        await ws.send_json(
            {
                "type": "banner",
                "text": f"{node.name} ({node.nos}) console — NetGeo\n{node.name}> ",
            }
        )
    except NotFound:
        with contextlib.suppress(Exception):
            await ws.send_json({"type": "error", "text": "node not found"})
        with contextlib.suppress(Exception):
            await ws.close()
        return
    except WebSocketDisconnect:
        return

    try:
        while True:
            raw = await ws.receive_text()
            # The frontend sends JSON-wrapped input: {"type":"input","data":"<cmd>"}.
            # Fall back to treating the raw string as the command if parsing fails.
            cmd = raw
            try:
                payload = json.loads(raw)
                if isinstance(payload, dict) and payload.get("type") == "input":
                    cmd = str(payload.get("data", ""))
            except Exception:
                pass
            await ws.send_json(
                {"type": "output", "node_id": node_id, "data": _handle_console(cmd)}
            )
    except WebSocketDisconnect:
        return


# ---------------------------------------------------------------------------
# /ws/collab  — realtime presence (Phase 3.1 multi-user collaboration)
# ---------------------------------------------------------------------------
#
# In-process presence rooms keyed by project id.  Like the topology bus this is
# a single-worker broadcaster for v0.1; production fans out across API workers
# via Redis pub/sub (infra/redis-design.md).  Protocol mirrors the frontend
# collab store exactly (frontend/src/store/collabStore.ts + api/types.ts):
#   server → client:  presence.sync | presence.join | presence.leave
#                     presence.cursor | presence.selection | crdt.op
#   client → server:  presence.cursor | presence.selection | crdt.op  (+ ping)
#
# The server is authoritative for peer identity: it assigns each connection a
# peer_id and stamps every relayed frame with it, ignoring any client-supplied
# peer_id so a peer cannot spoof another's cursor/selection.

_collab_rooms: dict[str, dict[str, WebSocket]] = {}
_collab_meta: dict[str, dict] = {}
_collab_lock = asyncio.Lock()


async def _collab_broadcast(
    project_key: str, frame: dict, *, exclude: str | None = None
) -> None:
    """Send a JSON frame to every peer in a room except ``exclude``."""
    for pid, sock in list(_collab_rooms.get(project_key, {}).items()):
        if pid == exclude:
            continue
        with contextlib.suppress(Exception):
            await sock.send_json(frame)


@router.websocket("/ws/collab")
async def ws_collab(
    ws: WebSocket,
    project: str | None = Query(default=None),
    token: str | None = Query(default=None),
):
    """Presence channel for concurrent topology editing.

    Authentication: ``?token=<jwt>`` query parameter required (same as the
    topology channel).  Scope is per ``?project=<id>`` so peers only see others
    editing the same project.  ``ping`` text frames are answered with ``pong``.
    """
    # --- RB-03: validate token BEFORE accepting the connection ---------------
    if not token:
        await _reject_ws(ws, code=4401, reason="Unauthorized: missing token")
        return
    try:
        user = await get_current_user_ws(token)
    except ValueError as exc:
        logger.debug("WS collab auth failed: %s", exc)
        await _reject_ws(ws, code=4401, reason="Unauthorized: invalid token")
        return

    await ws.accept()
    project_key = project or "_global"
    username = str(user.get("sub") or "user")
    # uuid suffix so the same user in two tabs is two distinct peers.
    peer_id = f"{username}:{uuid.uuid4().hex[:8]}"
    peer = {"id": peer_id, "name": username, "color": "", "lastSeen": int(time.time() * 1000)}

    async with _collab_lock:
        room = _collab_rooms.setdefault(project_key, {})
        existing = [_collab_meta[pid] for pid in room if pid in _collab_meta]
        room[peer_id] = ws
        _collab_meta[peer_id] = peer

    # Newcomer learns the current roster; everyone else learns about the newcomer.
    with contextlib.suppress(Exception):
        await ws.send_json({"type": "presence.sync", "peers": existing})
    await _collab_broadcast(
        project_key, {"type": "presence.join", "peer": peer}, exclude=peer_id
    )

    try:
        while True:
            raw = await ws.receive_text()
            if raw == "ping":
                await ws.send_text("pong")
                continue
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            if not isinstance(msg, dict):
                continue
            mtype = msg.get("type")
            if mtype == "presence.cursor":
                await _collab_broadcast(
                    project_key,
                    {"type": "presence.cursor", "peer_id": peer_id, "cursor": msg.get("cursor")},
                    exclude=peer_id,
                )
            elif mtype == "presence.selection":
                await _collab_broadcast(
                    project_key,
                    {"type": "presence.selection", "peer_id": peer_id, "selection": msg.get("selection")},
                    exclude=peer_id,
                )
            elif mtype == "crdt.op":
                op = msg.get("op")
                if isinstance(op, dict):
                    await _collab_broadcast(
                        project_key, {"type": "crdt.op", "op": op}, exclude=peer_id
                    )
            # Unknown frame types are ignored (forward-compatible).
    except WebSocketDisconnect:
        pass
    finally:
        async with _collab_lock:
            room = _collab_rooms.get(project_key)
            if room is not None:
                room.pop(peer_id, None)
                if not room:
                    _collab_rooms.pop(project_key, None)
            _collab_meta.pop(peer_id, None)
        await _collab_broadcast(
            project_key, {"type": "presence.leave", "peer_id": peer_id}
        )


def _handle_console(line: str) -> str:
    line = line.strip()
    if line in ("?", "help"):
        return "available (stub): show version | show interfaces | ping <node>\n"
    if line.startswith("show version"):
        return "NetGeo ForgeOS, Version 0.1 — sim mode\n"
    if line.startswith("show interfaces"):
        return "(interfaces rendered from node model in a future build)\n"
    return f"% Unknown command: {line}\n"
