"""Broadcast helpers: turn a store mutation into realtime bus events.

Endpoints call these after a successful create/update/delete so connected
``/ws/topology`` clients receive both the entity delta *and* a freshly recomputed
wireless plan (links + coverage) for the affected project. Recomputing server
-side — rather than trusting each client to redo the RF math — guarantees every
viewer agrees on RSSI and which links are feasible.

All helpers are best-effort and never raise into the request path: a broadcast
failure must not fail the user's POST/PATCH.
"""
from __future__ import annotations

import logging

from app.models import Link, Node
from app.services import wireless as wsvc
from app.services.events import get_bus
from app.store import MemoryRepository
from app.store import NotFound

logger = logging.getLogger("netforge.notify")


async def _publish_plan(repo: MemoryRepository, project_id: str) -> None:
    try:
        topo = await repo.topology(project_id)
    except NotFound:
        return
    plan = wsvc.plan_topology(topo)
    get_bus().publish(
        {"type": "wireless.plan", **plan.model_dump(mode="json")}, project_id
    )


async def node_changed(repo: MemoryRepository, node: Node) -> None:
    """A node was created or updated."""
    try:
        get_bus().publish(
            {"type": "node.updated", "node": node.model_dump(mode="json")},
            node.project_id,
        )
        await _publish_plan(repo, node.project_id)
    except Exception:  # pragma: no cover - broadcast is best-effort
        logger.exception("node_changed broadcast failed for %s", node.id)


async def node_removed(repo: MemoryRepository, project_id: str, node_id: str) -> None:
    try:
        get_bus().publish(
            {"type": "node.deleted", "node_id": node_id}, project_id
        )
        await _publish_plan(repo, project_id)
    except Exception:  # pragma: no cover
        logger.exception("node_removed broadcast failed for %s", node_id)


async def link_changed(repo: MemoryRepository, link: Link) -> None:
    try:
        get_bus().publish(
            {"type": "link.updated", "link": link.model_dump(mode="json")},
            link.project_id,
        )
    except Exception:  # pragma: no cover
        logger.exception("link_changed broadcast failed for %s", link.id)


async def link_removed(project_id: str | None, link_id: str) -> None:
    try:
        get_bus().publish({"type": "link.deleted", "link_id": link_id}, project_id)
    except Exception:  # pragma: no cover
        logger.exception("link_removed broadcast failed for %s", link_id)


__all__ = ["node_changed", "node_removed", "link_changed", "link_removed"]
