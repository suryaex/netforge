"""In-app update endpoints.

GET  /api/update/check   — read-only; compare running version with GitHub.
GET  /api/update/status  — progress reported by scripts/self-update.sh.
POST /api/update/apply   — trigger pull+rebuild+restart (guarded by UPDATE_TOKEN).

NetForge has no auth layer yet, so the *mutating* endpoint requires a shared
secret supplied via the ``X-Update-Token`` header and matched against
``settings.UPDATE_TOKEN``. With no token configured, applying is disabled.
"""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, status

from app.core.config import get_settings
from app.services import updater

router = APIRouter(tags=["update"])


@router.get("/update/check")
async def update_check() -> dict:
    return updater.check()


@router.get("/update/status")
async def update_status() -> dict:
    return updater.status()


@router.post("/update/apply")
async def update_apply(x_update_token: str | None = Header(default=None)) -> dict:
    settings = get_settings()
    if not settings.UPDATE_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Applying updates from the app is disabled (set UPDATE_TOKEN).",
        )
    if x_update_token != settings.UPDATE_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid update token.",
        )
    return updater.apply()
