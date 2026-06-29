"""Authentication endpoints.

POST /api/auth/login  — exchange credentials for a JWT access token (public)
GET  /api/auth/me     — return the current user's identity   (requires auth)

The login endpoint is intentionally public — no Depends(get_current_user) is
injected here; the router is included in api/__init__.py WITHOUT the auth
dependency so login is always reachable.

The /me endpoint applies get_current_user at the handler level, which lets the
auth contract file and the frontend clearly see that every call to /me must
carry a valid Bearer token.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.security import authenticate_user, check_rate_limit, create_access_token
from app.exceptions.base import Unauthorized

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, request: Request) -> TokenResponse:
    """Exchange username + password for a signed HS256 JWT access token.

    Rate-limited: 10 requests per minute per source IP (enforced by
    RateLimitMiddleware in main.py; this handler adds a second layer via
    check_rate_limit for defence in depth when the middleware is bypassed
    in unit tests).

    On success returns:
        {"access_token": "<jwt>", "token_type": "bearer", "expires_in": <seconds>}

    On failure always returns 401 UNAUTHORIZED with a generic message — the
    response never reveals whether the username or the password was wrong.
    """
    # In-handler rate-limit guard (defence in depth; middleware is the primary layer)
    client_ip = request.client.host if request.client else "unknown"
    if not check_rate_limit(f"login:{client_ip}", max_calls=10, window_seconds=60.0):
        # Re-use Unauthorized so the response envelope stays consistent.
        # 429 is handled by the middleware; here we just abort the handler.
        raise Unauthorized("Too many login attempts. Please wait and try again.")

    user = authenticate_user(body.username, body.password)
    if user is None:
        logger.warning("Failed login attempt for username=%r from %s", body.username, client_ip)
        # Generic message — never reveal whether it's the username or password.
        raise Unauthorized("Invalid username or password")

    settings = get_settings()
    expires_in = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    token = create_access_token(
        sub=user["sub"],
        role=user["role"],
        secret=settings.SECRET_KEY,
        expires_in=expires_in,
    )
    logger.info("Successful login for username=%r from %s", body.username, client_ip)
    return TokenResponse(access_token=token, token_type="bearer", expires_in=expires_in)


@router.get("/me")
async def me(current_user: dict = Depends(get_current_user)) -> dict:
    """Return the identity of the currently authenticated user.

    Requires:  Authorization: Bearer <access_token>
    """
    return {
        "username": current_user["sub"],
        "role": current_user["role"],
    }
