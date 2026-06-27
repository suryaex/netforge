#!/bin/sh
# =============================================================================
# NetForge backend entrypoint
# Validates env vars, waits for Postgres and Redis, then starts the server.
# Any CMD arguments are exec'd at the end so docker-compose command overrides
# (e.g. --reload) pass through cleanly.
# =============================================================================
set -e

# ---------------------------------------------------------------------------
# 1. Validate required env vars
# ---------------------------------------------------------------------------
MISSING=""
for VAR in DATABASE_URL REDIS_URL; do
    eval "VAL=\$$VAR"
    if [ -z "$VAL" ]; then
        MISSING="$MISSING $VAR"
    fi
done

if [ -n "$MISSING" ]; then
    echo "[entrypoint] ERROR: required env vars not set:$MISSING" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# 2. Parse connection params from URLs
# ---------------------------------------------------------------------------
# DATABASE_URL format: postgresql+asyncpg://user:pass@host:port/db
PG_HOST=$(echo "$DATABASE_URL" | sed -E 's|.*@([^:/]+)[:/].*|\1|')
PG_PORT=$(echo "$DATABASE_URL" | sed -E 's|.*@[^:]+:([0-9]+)/.*|\1|')
PG_USER=$(echo "$DATABASE_URL" | sed -E 's|.*://([^:]+):.*|\1|')

# REDIS_URL format: redis://host:port/db
REDIS_HOST=$(echo "$REDIS_URL" | sed -E 's|redis://([^:]+):.*|\1|')
REDIS_PORT=$(echo "$REDIS_URL" | sed -E 's|redis://[^:]+:([0-9]+).*|\1|')

# Fallbacks
PG_HOST="${PG_HOST:-postgres}"
PG_PORT="${PG_PORT:-5432}"
PG_USER="${PG_USER:-netforge}"
REDIS_HOST="${REDIS_HOST:-redis}"
REDIS_PORT="${REDIS_PORT:-6379}"

# ---------------------------------------------------------------------------
# 3. Wait for PostgreSQL (max 30s)
# ---------------------------------------------------------------------------
echo "[entrypoint] Waiting for PostgreSQL at ${PG_HOST}:${PG_PORT}..."
ELAPSED=0
until pg_isready -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -q; do
    ELAPSED=$((ELAPSED + 2))
    if [ "$ELAPSED" -ge 30 ]; then
        echo "[entrypoint] ERROR: PostgreSQL not ready after 30s" >&2
        exit 1
    fi
    sleep 2
done
echo "[entrypoint] PostgreSQL is ready."

# ---------------------------------------------------------------------------
# 4. Wait for Redis (max 30s)
# ---------------------------------------------------------------------------
echo "[entrypoint] Waiting for Redis at ${REDIS_HOST}:${REDIS_PORT}..."
ELAPSED=0
until redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" ping 2>/dev/null | grep -q "PONG"; do
    ELAPSED=$((ELAPSED + 2))
    if [ "$ELAPSED" -ge 30 ]; then
        echo "[entrypoint] ERROR: Redis not ready after 30s" >&2
        exit 1
    fi
    sleep 2
done
echo "[entrypoint] Redis is ready."

# ---------------------------------------------------------------------------
# 5. Hand off to CMD (uvicorn, or whatever docker-compose overrides with)
# ---------------------------------------------------------------------------
echo "[entrypoint] Starting: $*"
exec "$@"
