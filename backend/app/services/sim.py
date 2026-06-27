"""Simulation service — adapts the persistence model to the engine.

Builds an engine :class:`NetworkModel` (engine's own shape) from a stored
:class:`Topology`, runs the discrete-event kernel, and returns a JSON-able
result. Bits/s ↔ Mbps conversion happens here: the API/schema speak **Mbps**
(human-friendly), the engine speaks **bits/s** (physics).
"""
from __future__ import annotations

import logging

from app.models import Topology
from engine import (
    InterfaceModel,
    LinkModel,
    NetworkModel,
    NodeModel,
    Packet,
    Simulation,
    SimulationConfig,
)

logger = logging.getLogger("netforge.sim")

_MBPS = 1_000_000  # Mbps -> bits/s


def build_model(topo: Topology) -> NetworkModel:
    model = NetworkModel()
    for n in topo.nodes:
        model.add_node(
            NodeModel(
                id=n.id,
                name=n.name,
                kind=str(n.kind),
                nos=str(n.nos),
                mode=str(n.mode),
                interfaces=[
                    InterfaceModel(
                        id=i.id,
                        node_id=n.id,
                        name=i.name,
                        type=str(i.type),
                        ips=list(i.ip),
                        mac=i.mac,
                        speed=i.speed * _MBPS,
                        mtu=i.mtu,
                        peer_link_id=i.peer_link_id,
                    )
                    for i in n.interfaces
                ],
                status="up",
            )
        )
    for l in topo.links:
        model.add_link(
            LinkModel(
                id=l.id,
                a_iface=l.a_iface,
                b_iface=l.b_iface,
                type=str(l.type),
                bandwidth=l.bandwidth * _MBPS,
                delay=l.delay / 1000.0,   # ms -> s
                loss=l.loss,
                mtu=l.mtu,
                # Honor operational state: a link toggled down/admin_down in the
                # UI must actually stop carrying traffic. Without this the engine
                # left every link up=True, so disabling a link had no effect on
                # the run (packets were still delivered over a "down" link).
                up=str(l.status) == "up",
            )
        )
    return model


def run_once(topo: Topology, seed: int = 0, horizon: float | None = None) -> dict:
    """Build the model, inject one probe between the first two reachable hosts,
    run synchronously, and return a result dict. A minimal-but-real proof that
    the kernel processes the user's topology."""
    model = build_model(topo)
    sim = Simulation(model, SimulationConfig(seed=seed, horizon=horizon))

    node_ids = list(model.nodes)
    probes = 0
    # probe every ordered pair sparsely so large topologies stay cheap
    for src in node_ids[: min(len(node_ids), 8)]:
        for dst in node_ids:
            if src == dst:
                continue
            if model.shortest_path(src, dst):
                sim.inject(Packet(src=src, dst=dst, proto="icmp"))
                probes += 1
                break

    result = sim.run().as_dict()
    result["probes_injected"] = probes
    result["topology"] = model.stats
    return result
