"""Security utilities — stdlib-only, no external crypto dependencies.

Provides:
  * JWT creation / verification  (HS256 via hmac + hashlib)
  * Password hashing             (PBKDF2-HMAC-SHA256 via hashlib)
  * In-memory user store         (single admin account; no DB)
  * In-process sliding-window rate limiter

All of these use only the Python standard library so the backend has
zero new package dependencies for the auth layer.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from collections import defaultdict

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# JWT — HS256, stdlib only
# ---------------------------------------------------------------------------

# Pre-encode the fixed header once.
_JWT_HEADER_B64 = (
    base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').rstrip(b"=").decode()
)
_REQUIRED_CLAIMS = ("sub", "exp", "iat", "jti", "role")


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    pad = 4 - len(s) % 4
    if pad != 4:
        s += "=" * pad
    return base64.urlsafe_b64decode(s)


def create_access_token(sub: str, role: str, secret: str, expires_in: int = 3600) -> str:
    """Return a signed HS256 JWT string.

    Claims: sub, role, iat, exp, jti (random 128-bit nonce for replay deterrence).
    """
    now = int(time.time())
    payload = {
        "sub": sub,
        "role": role,
        "iat": now,
        "exp": now + expires_in,
        "jti": secrets.token_hex(16),
    }
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{_JWT_HEADER_B64}.{payload_b64}"
    sig = hmac.new(
        secret.encode("utf-8"),
        signing_input.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return f"{signing_input}.{_b64url_encode(sig)}"


def decode_access_token(token: str, secret: str) -> dict:
    """Decode and verify an HS256 JWT.  Returns the claims dict on success.

    Raises ValueError with a descriptive message on any failure (expired,
    bad signature, malformed, wrong algorithm, missing required claim).
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Malformed token: expected 3 dot-separated segments")
    header_b64, payload_b64, sig_b64 = parts

    # Verify algorithm declared in header.
    try:
        header = json.loads(_b64url_decode(header_b64))
    except Exception:
        raise ValueError("Malformed token: cannot decode header")
    if header.get("alg") != "HS256":
        raise ValueError(f"Unsupported algorithm: {header.get('alg')!r}")

    # Constant-time signature verification.
    signing_input = f"{header_b64}.{payload_b64}"
    expected_sig = hmac.new(
        secret.encode("utf-8"),
        signing_input.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    try:
        provided_sig = _b64url_decode(sig_b64)
    except Exception:
        raise ValueError("Malformed token: cannot decode signature")
    if not hmac.compare_digest(expected_sig, provided_sig):
        raise ValueError("Invalid token signature")

    # Decode payload.
    try:
        claims: dict = json.loads(_b64url_decode(payload_b64))
    except Exception:
        raise ValueError("Malformed token: cannot decode payload")

    # Check expiry before returning claims.
    if int(time.time()) > claims.get("exp", 0):
        raise ValueError("Token expired")

    # Require standard claims so callers can always access them safely.
    for claim in _REQUIRED_CLAIMS:
        if claim not in claims:
            raise ValueError(f"Token missing required claim: {claim!r}")

    return claims


# ---------------------------------------------------------------------------
# Password hashing — PBKDF2-HMAC-SHA256 (stdlib)
# ---------------------------------------------------------------------------

_PBKDF2_ITERATIONS = 260_000   # OWASP 2023 recommendation for SHA-256
_PBKDF2_HASH = "sha256"
_SALT_BYTES = 16


def hash_password(password: str) -> str:
    """Hash a password.  Returns a self-contained portable string.

    Format: ``pbkdf2:sha256:<iterations>$<salt_hex>$<dk_hex>``
    """
    salt = os.urandom(_SALT_BYTES)
    dk = hashlib.pbkdf2_hmac(
        _PBKDF2_HASH, password.encode("utf-8"), salt, _PBKDF2_ITERATIONS
    )
    return f"pbkdf2:{_PBKDF2_HASH}:{_PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, hashed: str) -> bool:
    """Constant-time password verification.  Returns True iff password matches."""
    try:
        prefix, rest = hashed.split("$", 1)
        _scheme, hash_algo, iter_str = prefix.split(":")
        iterations = int(iter_str)
        salt_hex, dk_hex = rest.split("$", 1)
        salt = bytes.fromhex(salt_hex)
        stored_dk = bytes.fromhex(dk_hex)
        candidate_dk = hashlib.pbkdf2_hmac(
            hash_algo, password.encode("utf-8"), salt, iterations
        )
        return hmac.compare_digest(stored_dk, candidate_dk)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# In-memory user store  (single admin account; no database dependency)
# ---------------------------------------------------------------------------

# { username: {"hashed_password": str, "role": str} }
_users: dict[str, dict] = {}


def init_admin_user(username: str, password: str) -> None:
    """Hash and store the admin user.  Idempotent — skips if user exists.

    Called once at application startup from the lifespan hook.
    """
    if username in _users:
        return  # already seeded (e.g. test fixtures run before lifespan)
    _users[username] = {
        "hashed_password": hash_password(password),
        "role": "admin",
    }
    logger.info("Admin user %r initialised.", username)


def authenticate_user(username: str, password: str) -> dict | None:
    """Return {"sub": username, "role": role} if credentials are valid, else None.

    Always performs a full PBKDF2 round-trip even for unknown usernames to
    prevent username enumeration via timing side-channel.
    """
    user = _users.get(username)
    if not user:
        # Consume the same time as a real verify so username exists / not
        # cannot be distinguished by response latency.
        verify_password(password, hash_password("___dummy_constant___"))
        return None
    if not verify_password(password, user["hashed_password"]):
        return None
    return {"sub": username, "role": user["role"]}


# ---------------------------------------------------------------------------
# In-process sliding-window rate limiter
# ---------------------------------------------------------------------------

# { bucket_key: [monotonic_timestamp, ...] }
_rate_buckets: dict[str, list[float]] = defaultdict(list)


def check_rate_limit(key: str, max_calls: int, window_seconds: float) -> bool:
    """Return True if the request is within the rate limit, False if exceeded.

    Uses a sliding window log.  Thread/coroutine safe for asyncio (single-
    threaded event loop — no concurrent mutation between the check and append).
    """
    now = time.monotonic()
    cutoff = now - window_seconds
    bucket = _rate_buckets[key]
    # Evict expired entries (list is ordered oldest→newest).
    while bucket and bucket[0] < cutoff:
        bucket.pop(0)
    if len(bucket) >= max_calls:
        return False
    bucket.append(now)
    return True
