"""HTTP + WebSocket API. Endpoints mirror MASTER_SPEC §4 and the frontend
``src/api/client.ts`` exactly."""
from __future__ import annotations

from fastapi import APIRouter

from app.api import configs, links, nodes, projects, scenarios, simulate, update

api_router = APIRouter(prefix="/api")
api_router.include_router(projects.router)
api_router.include_router(nodes.router)
api_router.include_router(links.router)
api_router.include_router(scenarios.router)
api_router.include_router(simulate.router)
api_router.include_router(configs.router)
api_router.include_router(update.router)
