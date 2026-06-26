"""Wireless / RF planning endpoints (map mode).

Authoritative server-side signal propagation: the frontend may show an instant
FSPL estimate while dragging, but these endpoints — backed by the engine's full
Friis link budget (antenna gain, misc loss, receiver sensitivity, noise floor) —
are the source of truth that gets persisted and broadcast over ``/ws/topology``.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import repo, translate_not_found
from app.models import (
    CoverageResult,
    ElevationPoint,
    ElevationProfile,
    LinkBudgetRequest,
    LinkBudgetResult,
    LosCheckRequest,
    LosCheckResult,
    WirelessPlanResult,
)
from app.services import elevation as esvc
from app.services import wireless as wsvc
from app.store import MemoryRepository
from app.store import NotFound as StoreNotFound
from engine import wireless as rf

router = APIRouter(prefix="/wireless", tags=["wireless"])


@router.post("/link-budget", response_model=LinkBudgetResult)
async def link_budget(body: LinkBudgetRequest):
    """Single point-to-point link budget. Give ``distance_m`` or both endpoint
    coordinates (Haversine-derived distance). Optional ITU-R P.838 rain fade."""
    try:
        budget = wsvc.link_budget_between(
            body.tx,
            body.rx,
            distance_m=body.distance_m,
            a_lat=body.a_lat,
            a_lon=body.a_lon,
            b_lat=body.b_lat,
            b_lon=body.b_lon,
            rain_rate_mm_hr=body.rain_rate_mm_hr,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return LinkBudgetResult(**budget.as_dict())


@router.get("/elevation", response_model=ElevationProfile)
async def elevation_profile(
    a_lat: float = Query(..., ge=-90, le=90),
    a_lon: float = Query(..., ge=-180, le=180),
    b_lat: float = Query(..., ge=-90, le=90),
    b_lon: float = Query(..., ge=-180, le=180),
    samples: int = Query(24, ge=2, le=128),
):
    """Sampled terrain elevation profile between two points (proxy to the
    elevation provider). 503 if the provider is unreachable."""
    try:
        pts = await esvc.fetch_profile(a_lat, a_lon, b_lat, b_lon, samples)
    except esvc.ElevationUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"elevation provider: {exc}") from exc
    total = pts[-1]["distance_m"] if pts else 0.0
    return ElevationProfile(
        samples=len(pts),
        total_distance_m=total,
        points=[ElevationPoint(**p) for p in pts],
    )


@router.post("/los-check", response_model=LosCheckResult)
async def los_check(body: LosCheckRequest):
    """Terrain line-of-sight + Fresnel clearance between two endpoints.

    Uses a caller-supplied ``profile`` if present (offline), otherwise fetches
    terrain from the elevation provider."""
    distance_m = rf.haversine_m(body.a_lat, body.a_lon, body.b_lat, body.b_lon)

    if body.profile is not None:
        profile = [p.model_dump() for p in body.profile]
        out_profile = None
    else:
        try:
            profile = await esvc.fetch_profile(
                body.a_lat, body.a_lon, body.b_lat, body.b_lon, body.samples
            )
        except esvc.ElevationUnavailable as exc:
            raise HTTPException(
                status_code=503, detail=f"elevation provider: {exc}"
            ) from exc
        out_profile = ElevationProfile(
            samples=len(profile),
            total_distance_m=profile[-1]["distance_m"] if profile else 0.0,
            points=[ElevationPoint(**p) for p in profile],
        )

    res = esvc.analyse_los(
        distance_m=distance_m,
        frequency_ghz=body.frequency_ghz,
        tx_height_m=body.tx_height_m,
        rx_height_m=body.rx_height_m,
        profile=profile,
    )
    return LosCheckResult(profile=out_profile, **res.as_dict())


@router.get("/plan/{project_id}", response_model=WirelessPlanResult)
async def plan_project(project_id: str, r: MemoryRepository = Depends(repo)):
    """Compute the full wireless plan (links + coverage) for a project's
    geo-placed nodes."""
    try:
        topo = await r.topology(project_id)
    except StoreNotFound as exc:
        raise translate_not_found(exc) from exc
    return wsvc.plan_topology(topo)


@router.get("/coverage/{node_id}", response_model=CoverageResult)
async def node_coverage(node_id: str, r: MemoryRepository = Depends(repo)):
    """Theoretical coverage radius (m) for a single serving node."""
    try:
        node = await r.get_node(node_id)
    except StoreNotFound as exc:
        raise translate_not_found(exc) from exc
    return CoverageResult(node_id=node_id, radius_m=wsvc.coverage_radius(node))
