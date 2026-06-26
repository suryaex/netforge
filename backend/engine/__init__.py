"""NetForge simulation engine.

A hybrid network simulation core: a deterministic *discrete-event simulation*
(DES) kernel for scale (thousands of nodes), plus a pluggable *emulation*
adaptor layer (containerlab / Docker / Podman) for NOS-accurate nodes.

The engine is intentionally framework-agnostic: it has **no dependency on
FastAPI, SQLAlchemy or the web layer**. It consumes a plain in-memory
``NetworkModel`` (built from the app's data model) and produces a stream of
``SimEvent`` / metrics that the web layer relays over WebSocket.

Public surface:
    - ``EventQueue``      — priority queue keyed by simulation time
    - ``Scheduler``       — drains the queue, advances the virtual clock
    - ``Simulation``      — orchestrates a run over a ``NetworkModel``
    - ``NetworkModel``    — node/link/interface graph the engine operates on
    - ``Packet`` / ``LinkModel`` — packet & link propagation primitives
    - ``NodeRuntime``     — per-node behaviour hook (sim mode)
    - ``EmulationAdaptor``— ABC for emul-mode backends (containerlab/Docker)
"""
from __future__ import annotations

from engine.events import EventQueue, EventType, SimEvent
from engine.model import InterfaceModel, LinkModel, NetworkModel, NodeModel
from engine.packet import Packet
from engine.runtime import NodeRuntime
from engine.scheduler import Scheduler
from engine.simulation import Simulation, SimulationConfig, SimulationResult
from engine.wireless import (
    GeoDevice,
    LinkBudget,
    LinkQuality,
    LosResult,
    PlannedLink,
    Radio,
    fresnel_radius_m,
    fspl_db,
    haversine_m,
    line_of_sight,
    link_budget,
    max_range_m,
    plan_links,
    rain_attenuation_db,
    rain_specific_attenuation_db_km,
)

__all__ = [
    "EventQueue",
    "EventType",
    "SimEvent",
    "InterfaceModel",
    "LinkModel",
    "NetworkModel",
    "NodeModel",
    "Packet",
    "NodeRuntime",
    "Scheduler",
    "Simulation",
    "SimulationConfig",
    "SimulationResult",
    # wireless / RF
    "Radio",
    "GeoDevice",
    "LinkBudget",
    "LinkQuality",
    "LosResult",
    "PlannedLink",
    "fspl_db",
    "haversine_m",
    "fresnel_radius_m",
    "line_of_sight",
    "link_budget",
    "max_range_m",
    "plan_links",
    "rain_attenuation_db",
    "rain_specific_attenuation_db_km",
]

__version__ = "0.1.0"
