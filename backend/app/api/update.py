"""In-app update endpoints.

GET  /api/update/check   — read-only; compare running version with GitHub.
GET  /api/update/status  — progress reported by scripts/self-update.sh.
POST /api/update/apply   — trigger pull+rebuild+restart (guarded by UPDATE_TOKEN).

NetForge has no auth layer yet, so the *mutating* endpoint requires a shared
secret supplied via the ``X-Update-Token`` header and matched against
``settings.UPDATE_TOKEN``. With no token configured, applying is disabled.

Handlers are intentionally **synchronous** ``def`` functions. ``updater.check``
and ``updater.apply`` perform *blocking* network/subprocess I/O; declaring the
routes ``async`` would run that I/O directly on the asyncio event loop and stall
every other in-flight request (which is exactly how the UI ends up reporting the
backend as unreachable). FastAPI runs plain ``def`` handlers in a threadpool, so
the blocking work never starves the event loop.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Header, HTTPException, status

from app.core.config import get_settings
from app.services import updater

logger = logging.getLogger(__name__)

router = APIRouter(tags=["update"])


@router.get("/update/check")
def update_check() -> dict:
    # check() is defensive and degrades gracefully, but guard the route anyway so
    # an unexpected failure surfaces as a structured payload instead of a 500 —
    # the frontend distinguishes "GitHub unreachable" from "backend unreachable".
    try:
        return updater.check()
    except Exception:  # noqa: BLE001 — last-resort guard; never 500 a read-only check
        logger.exception("update_check failed unexpectedly")
        return {
            "current": get_settings().APP_VERSION,
            "latest": None,
            "update_available": False,
            "error": "Update check failed unexpectedly on the backend.",
        }


@router.get("/update/status")
def update_status() -> dict:
    return updater.status()


@router.post("/update/apply")
def update_apply(x_update_token: str | None = Header(default=None)) -> dict:
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
