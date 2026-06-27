"""Service-layer regression: persistence model -> engine model translation.

Guards the seam in ``app/services/sim.py``: operational state (link status) and
unit conversions must survive the hop from the stored :class:`Topology` into the
engine's :class:`NetworkModel`.
"""
from __future__ import annotations

from app.models import Interface, Link, Node, Project, Topology
from app.services.sim import build_model


def _topo() -> Topology:
    proj = Project(id="p1", name="p1")
    a = Node(
        id="A", project_id="p1", name="A",
        interfaces=[Interface(id="A-e0", node_id="A", name="e0")],
    )
    b = Node(
        id="B", project_id="p1", name="B",
        interfaces=[Interface(id="B-e0", node_id="B", name="e0")],
    )
    link = Link(id="lAB", project_id="p1", a_iface="A-e0", b_iface="B-e0",
                bandwidth=1000, delay=1.0, status="down")
    return Topology(project=proj, nodes=[a, b], links=[link])


def test_build_model_honors_link_status():
    model = build_model(_topo())
    assert model.links["lAB"].up is False, "down link must map to up=False"


def test_build_model_converts_units():
    topo = _topo()
    topo.links[0].status = "up"
    model = build_model(topo)
    link = model.links["lAB"]
    assert link.up is True
    assert link.bandwidth == 1000 * 1_000_000   # Mbps -> bits/s
    assert abs(link.delay - 0.001) < 1e-9        # ms -> s
