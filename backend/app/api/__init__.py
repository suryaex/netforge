"""HTTP + WebSocket API. Endpoints mirror MASTER_SPEC §4 and the frontend
``src/api/client.ts`` exactly.

Auth strategy (RB-01):
  * The auth router (/api/auth/login, /api/auth/me) is included WITHOUT the
    auth dependency so that /login is publicly reachable.
  * Every other router is included with ``dependencies=[Depends(get_current_user)]``
    so authentication is enforced at the router level — individual handlers do
    not need to repeat the dependency.
  * Health/readiness endpoints defined in main.py stay public.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api import (
    auth,
    configs,
    device_types,
    links,
    nodes,
    projects,
    scenarios,
    signal,
    simulate,
    system,
    update,
    wireless,
)
from app.api.deps import get_current_user

# Centralised auth dependency list — applied to every protected router.
_require_auth = [Depends(get_current_user)]

api_router = APIRouter(prefix="/api")

# ---- Public ----------------------------------------------------------------
# Login is intentionally unauthenticated.  /me protects itself at handler level.
api_router.include_router(auth.router)

# ---- Protected (JWT required) ----------------------------------------------
api_router.include_router(projects.router, dependencies=_require_auth)
api_router.include_router(nodes.router, dependencies=_require_auth)
api_router.include_router(links.router, dependencies=_require_auth)
api_router.include_router(scenarios.router, dependencies=_require_auth)
api_router.include_router(simulate.router, dependencies=_require_auth)
api_router.include_router(configs.router, dependencies=_require_auth)
api_router.include_router(system.router, dependencies=_require_auth)
api_router.include_router(update.router, dependencies=_require_auth)   # RB-05
api_router.include_router(signal.router, dependencies=_require_auth)
api_router.include_router(device_types.router, dependencies=_require_auth)
api_router.include_router(wireless.router, dependencies=_require_auth)
