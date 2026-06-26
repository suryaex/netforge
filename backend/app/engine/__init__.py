"""NetForge app-layer engine extensions.

This sub-package extends the framework-agnostic ``engine/`` core with models
that depend on real-world data sources (elevation APIs, empirical propagation
tables) and higher-level planning logic (auto-topology, channel planning).

Public modules
--------------
propagation  — FSPL, Okumura-Hata, ITU-R P.452, ITU-R P.838 rain attenuation
terrain      — Open-Elevation lookup, Fresnel zone, LOS obstruction check
topology     — auto-connect, link-budget, channel planning for geo-placed devices
"""
from __future__ import annotations

from app.engine import propagation, terrain, topology  # noqa: F401

__all__ = ["propagation", "terrain", "topology"]
