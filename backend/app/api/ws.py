"""WebSocket endpoints: live topology/telemetry and per-node console.

For v0.1 these are in-process broadcasters. Production fans out via Redis
pub/sub (infra/redis-design.md) so multiple API workers share one event bus.

Security note (security/threat-model.md): ``node_id`` on the console socket
MUST be re-authorized server-side once auth lands — never trust the path param
alone for access to a device console.
"""
from __future__ import annotations

import asyncio
import contextlib

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.events import get_bus
from app.services import wireless as wsvc
from app.store import get_repo
from app.store import NotFound

router = APIRouter()


@router.websocket("/ws/topology")
async def ws_topology(ws: WebSocket, project: str | None = None):
    """Event-driven topology stream.

    On connect we push a full ``snapshot`` (plus the current ``wireless.plan``
    when a project is scoped), then relay deltas published on the in-process bus
    by mutating endpoints — so the moment a device is placed/moved on the map,
    every open client sees the recomputed links and RSSI without polling.

    A client may scope the stream with ``?project=<id>``; otherwise it receives
    global events. ``ping`` text frames are answered with ``pong`` for heartbeat.
    """
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
            await ws.send_json({"type": "error", "reason": "project not found"})

    # --- fan-out loop -------------------------------------------------------
    async def pump_client() -> None:
        """Relay client → server frames (ping/pong). Raises on disconnect."""
        while True:
            msg = await ws.receive_text()
            if msg == "ping":
                await ws.send_json({"type": "pong"})

    async with bus.subscription(project) as events:

        async def pump_bus() -> None:
            async for event in events:
                await ws.send_json(event)

        client_task = asyncio.create_task(pump_client())
        bus_task = asyncio.create_task(pump_bus())
        try:
            await asyncio.wait(
                {client_task, bus_task}, return_when=asyncio.FIRST_COMPLETED
            )
        except WebSocketDisconnect:
            pass
        finally:
            for t in (client_task, bus_task):
                t.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await t


@router.websocket("/ws/console/{node_id}")
async def ws_console(ws: WebSocket, node_id: str):
    """A simulated device console. Echoes a banner then relays line input to a
    (stub) command handler. Real emul-mode attaches this to the container PTY."""
    await ws.accept()
    repo = get_repo()
    try:
        node = await repo.get_node(node_id)
        await ws.send_json({"type": "banner", "text": f"{node.name} ({node.nos}) console — NetForge\n{node.name}> "})
    except Exception:
        await ws.send_json({"type": "error", "text": "node not found"})
        await ws.close()
        return

    try:
        while True:
            line = await ws.receive_text()
            await ws.send_json({"type": "output", "text": _handle_console(line)})
    except WebSocketDisconnect:
        return


def _handle_console(line: str) -> str:
    line = line.strip()
    if line in ("?", "help"):
        return "available (stub): show version | show interfaces | ping <node>\n"
    if line.startswith("show version"):
        return "NetForge ForgeOS, Version 0.1 — sim mode\n"
    if line.startswith("show interfaces"):
        return "(interfaces rendered from node model in a future build)\n"
    return f"% Unknown command: {line}\n"
