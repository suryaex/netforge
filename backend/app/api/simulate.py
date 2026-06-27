"""Simulation control endpoints.

``POST /simulate`` runs the discrete-event kernel over a project's topology and
returns a result summary. The lifecycle endpoints (pause/resume/step/stop) are
the control surface the frontend SimulationBar drives; for v0.1 the in-process
runner executes synchronously, so they return the current run state. A
distributed run-manager (Redis-backed job queue, see infra/redis-design.md) is
the production target.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool

from app.api.deps import repo, translate_not_found
from app.exceptions.base import SimulationError
from app.models import SimulateRequest
from app.services import sim as sim_service
from app.store import MemoryRepository
from app.store import NotFound as StoreNotFound

router = APIRouter(tags=["simulate"])

# Minimal in-memory run registry (project_id -> last result/state).
_runs: dict[str, dict] = {}


@router.post("/simulate")
async def start_simulation(body: SimulateRequest, r: MemoryRepository = Depends(repo)):
    try:
        topo = await r.topology(body.project_id)
    except StoreNotFound as exc:
        raise translate_not_found(exc) from exc
    try:
        # The kernel is synchronous and CPU-bound; running it inline would block
        # the event loop (stalling every other request and the /ws/topology
        # stream) for the whole run. Offload to a worker thread.
        result = await run_in_threadpool(
            sim_service.run_once, topo, seed=body.seed, horizon=body.horizon
        )
    except Exception as exc:  # engine errors -> 422 with a clear message
        raise SimulationError(str(exc)) from exc
    state = {"project_id": body.project_id, "state": "completed", "result": result}
    _runs[body.project_id] = state
    return state


@router.post("/simulate/{project_id}/pause")
async def pause(project_id: str):
    return _transition(project_id, "paused")


@router.post("/simulate/{project_id}/resume")
async def resume(project_id: str):
    return _transition(project_id, "running")


@router.post("/simulate/{project_id}/step")
async def step(project_id: str):
    return _transition(project_id, "stepped")


@router.post("/simulate/{project_id}/stop")
async def stop(project_id: str):
    return _transition(project_id, "stopped")


def _transition(project_id: str, state: str) -> dict:
    run = _runs.get(project_id, {"project_id": project_id})
    run["state"] = state
    _runs[project_id] = run
    return run
