"""Link endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import repo, translate_not_found
from app.models import Link, LinkCreate, LinkUpdate
from app.services import notify
from app.store import MemoryRepository
from app.store import NotFound as StoreNotFound
from app.utils.ids import new_id

router = APIRouter(tags=["links"])


@router.post("/links", response_model=Link, status_code=201)
async def create_link(body: LinkCreate, r: MemoryRepository = Depends(repo)):
    link = Link(id=new_id(), **body.model_dump())
    created = await r.add_link(link)
    await notify.link_changed(r, created)
    return created


@router.get("/links/{link_id}", response_model=Link)
async def get_link(link_id: str, r: MemoryRepository = Depends(repo)):
    try:
        return await r.get_link(link_id)
    except StoreNotFound as exc:
        raise translate_not_found(exc) from exc


@router.patch("/links/{link_id}", response_model=Link)
async def update_link(link_id: str, patch: LinkUpdate, r: MemoryRepository = Depends(repo)):
    try:
        updated = await r.update_link(link_id, patch.model_dump(exclude_unset=True))
    except StoreNotFound as exc:
        raise translate_not_found(exc) from exc
    await notify.link_changed(r, updated)
    return updated


@router.delete("/links/{link_id}", status_code=200)
async def delete_link(link_id: str, r: MemoryRepository = Depends(repo)) -> dict:
    try:
        link = await r.get_link(link_id)
        await r.delete_link(link_id)
    except StoreNotFound as exc:
        raise translate_not_found(exc) from exc
    await notify.link_removed(link.project_id, link_id)
    return {"deleted": link_id}
