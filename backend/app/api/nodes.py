"""Node endpoints. Interfaces are created with the node (ids minted here if
the client did not supply them)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import repo, translate_not_found
from app.models import Node, NodeCreate, NodeUpdate
from app.services import notify
from app.store import MemoryRepository
from app.store import NotFound as StoreNotFound
from app.utils.ids import new_id

router = APIRouter(tags=["nodes"])


@router.post("/nodes", response_model=Node, status_code=201)
async def create_node(body: NodeCreate, r: MemoryRepository = Depends(repo)):
    nid = new_id()
    ifaces = [
        i if i.id else i.model_copy(update={"id": new_id(), "node_id": nid})
        for i in body.interfaces
    ]
    # ensure node_id is set even when client supplied iface ids
    ifaces = [i.model_copy(update={"node_id": nid}) for i in ifaces]
    node = Node(
        id=nid,
        project_id=body.project_id,
        name=body.name,
        kind=body.kind,
        nos=body.nos,
        mode=body.mode,
        x=body.x,
        y=body.y,
        lat=body.lat,
        lon=body.lon,
        radio=body.radio,
        interfaces=ifaces,
        intent=body.intent,
    )
    created = await r.add_node(node)
    await notify.node_changed(r, created)
    return created


@router.get("/nodes/{node_id}", response_model=Node)
async def get_node(node_id: str, r: MemoryRepository = Depends(repo)):
    try:
        return await r.get_node(node_id)
    except StoreNotFound as exc:
        raise translate_not_found(exc) from exc


@router.patch("/nodes/{node_id}", response_model=Node)
async def update_node(node_id: str, patch: NodeUpdate, r: MemoryRepository = Depends(repo)):
    try:
        updated = await r.update_node(node_id, patch.model_dump(exclude_unset=True))
    except StoreNotFound as exc:
        raise translate_not_found(exc) from exc
    await notify.node_changed(r, updated)
    return updated


@router.delete("/nodes/{node_id}", status_code=204)
async def delete_node(node_id: str, r: MemoryRepository = Depends(repo)):
    try:
        node = await r.get_node(node_id)
        await r.delete_node(node_id)
    except StoreNotFound as exc:
        raise translate_not_found(exc) from exc
    await notify.node_removed(r, node.project_id, node_id)
