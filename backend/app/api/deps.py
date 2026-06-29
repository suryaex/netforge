"""Shared API dependencies + store-error translation + JWT authentication.

RB-01: ``get_current_user`` is the central FastAPI dependency that verifies the
JWT on every protected route.  It is attached at router-include time in
``app/api/__init__.py`` so individual handlers do not need to repeat it.

RB-03: ``get_current_user_ws`` is the WebSocket variant — token comes as a
query-string parameter because browsers cannot send Authorization headers in
the WebSocket upgrade handshake.
"""
from __future__ import annotations

import logging

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import get_settings
from app.core.security import decode_access_token
from app.exceptions.base import NotFound as ApiNotFound
from app.exceptions.base import Unauthorized
from app.store import MemoryRepository, get_repo
from app.store import NotFound as StoreNotFound

logger = logging.getLogger(__name__)

# auto_error=False — we raise Unauthorized (→ our error envelope) instead of
# FastAPI's built-in HTTPException (→ different shape).
_bearer = HTTPBearer(auto_error=False)


def repo() -> MemoryRepository:
    return get_repo()


def translate_not_found(exc: StoreNotFound) -> ApiNotFound:
    """Map the storage-layer KeyError to the HTTP 404 envelope."""
    return ApiNotFound(f"resource '{exc.args[0] if exc.args else '?'}' not found")


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    """FastAPI dependency: extract and verify a Bearer JWT from the Authorization header.

    Returns the decoded claims dict on success.  Raises ``Unauthorized`` on any
    failure so the response matches the project's standard error envelope.

    Usage (router level — preferred):
        api_router.include_router(projects.router, dependencies=[Depends(get_current_user)])

    Usage (handler level):
        async def my_route(user: dict = Depends(get_current_user)): ...
    """
    if credentials is None:
        raise Unauthorized("Missing or malformed Authorization header")
    settings = get_settings()
    try:
        claims = decode_access_token(credentials.credentials, settings.SECRET_KEY)
    except ValueError as exc:
        logger.debug("JWT validation failed: %s", exc)
        raise Unauthorized(str(exc)) from exc
    return claims


async def get_current_user_ws(token: str) -> dict:
    """Validate a JWT for WebSocket connections.

    Token arrives as a URL query parameter (``?token=<jwt>``) because browsers
    cannot set the Authorization header on the WebSocket upgrade handshake.

    Returns the decoded claims dict on success.
    Raises ``ValueError`` on failure — callers must catch this and close the
    WebSocket with code 4401 BEFORE calling ``ws.accept()``.
    """
    settings = get_settings()
    return decode_access_token(token, settings.SECRET_KEY)
