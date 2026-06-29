"""NetGeo backend entrypoint.

FastAPI app assembling the §4 REST surface, the WebSocket endpoints, the shared
error envelope, CORS, JWT authentication (RB-01), and in-process rate limiting
(RB-14) — mirroring the secureops/storagehub app factory style.

Run:  uvicorn app.main:app --reload --port 8000
Smoke: python -c "from app.main import app; print('netgeo backend imports OK')"
"""
from __future__ import annotations

import json
import logging
import secrets
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.api.ws import router as ws_router
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.security import check_rate_limit, init_admin_user

logger = logging.getLogger(__name__)

settings = get_settings()


# ---------------------------------------------------------------------------
# RB-14: In-process rate-limit middleware
# ---------------------------------------------------------------------------

# Rules: (path, method, max_calls_per_window, window_seconds)
_RATE_LIMIT_RULES: list[tuple[str, str, int, float]] = [
    ("/api/auth/login", "POST", 10, 60.0),    # brute-force guard on login
    ("/api/update/apply", "POST", 5, 60.0),   # update trigger guard (RB-05)
]

_RATE_LIMITED_BODY = json.dumps(
    {"success": False, "error": {"code": "RATE_LIMITED", "message": "Too many requests. Please try again later."}}
).encode()


class RateLimitMiddleware:
    """Per-IP sliding-window rate limiter implemented as pure ASGI middleware.

    No external dependencies (no Redis, no slowapi). Uses the in-process
    sliding-window log from ``app.core.security.check_rate_limit``.

    Applied only to the endpoints listed in _RATE_LIMIT_RULES to avoid
    adding overhead to every request.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            path = scope.get("path", "")
            method = scope.get("method", "")
            for rule_path, rule_method, max_calls, window in _RATE_LIMIT_RULES:
                if path == rule_path and method == rule_method:
                    client_ip = self._client_ip(scope)
                    key = f"rl:{rule_path}:{client_ip}"
                    if not check_rate_limit(key, max_calls, window):
                        await self._send_429(send)
                        return
                    break
        await self.app(scope, receive, send)

    @staticmethod
    def _client_ip(scope: dict) -> str:
        """Best-effort source IP from the ASGI scope.

        Uses the direct TCP peer address for rate-limiting so that spoofed
        X-Forwarded-For headers cannot be used to bypass limits.
        """
        client = scope.get("client")
        if client:
            return client[0]
        return "unknown"

    @staticmethod
    async def _send_429(send: Any) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 429,
                "headers": [
                    [b"content-type", b"application/json"],
                    [b"retry-after", b"60"],
                ],
            }
        )
        await send({"type": "http.response.body", "body": _RATE_LIMITED_BODY})


# ---------------------------------------------------------------------------
# Admin user initialisation helper
# ---------------------------------------------------------------------------

def _init_admin_from_settings() -> None:
    """Seed the in-memory admin user from environment variables.

    Called once from the lifespan hook so settings are fully loaded.

    - If NETGEO_ADMIN_PASSWORD is set: use it.
    - If empty: auto-generate a random password, print it to stderr, and warn.
      The random password is ephemeral — lost on restart.  Set the env var
      to persist credentials across restarts.
    """
    username = settings.NETGEO_ADMIN_USER
    password = settings.NETGEO_ADMIN_PASSWORD

    if not password:
        password = secrets.token_urlsafe(16)
        logger.warning(
            "\n\n[SECURITY WARNING] NETGEO_ADMIN_PASSWORD is not set.\n"
            "Auto-generated ephemeral password for admin user %r: %s\n"
            "This password will change on every restart.\n"
            "Set NETGEO_ADMIN_PASSWORD in your .env file to make it persistent.\n",
            username,
            password,
        )

    init_admin_user(username, password)


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    _init_admin_from_settings()
    logger.info("NetGeo backend started (environment=%s)", settings.ENVIRONMENT)
    yield
    logger.info("NetGeo backend shutting down.")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="NetGeo — open-source large-scale network simulation platform.",
        lifespan=lifespan,
    )

    # RB-14: in-process rate limiter (outermost middleware so it runs before auth)
    app.add_middleware(RateLimitMiddleware)

    # RB-09: tightened CORS — explicit methods and headers instead of wildcards
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-API-Key", "X-Request-ID"],
    )

    register_exception_handlers(app)
    app.include_router(api_router)   # /api/*
    app.include_router(ws_router)    # /ws/*

    @app.get("/api/health", tags=["meta"])
    async def health() -> dict:
        """Public health check — no authentication required."""
        return {
            "status": "ok",
            "app": settings.APP_NAME,
            "version": settings.APP_VERSION,
        }

    return app


app = create_app()
