"""In-memory network model the engine simulates.

This is the engine's *own* representation, deliberately decoupled from the
persistence/ORM layer (``app.models``). The web layer builds a ``NetworkModel``
from a stored project and hands it to the engine. Keeping these separate means
the engine can be unit-tested and embedded without a database, and lets us pick
the most compute-friendly shape (a ``networkx`` graph + flat dicts) regardless
of how data is stored on disk.

Maps 1:1 onto MASTER_SPEC §4 (Node / Interface / Link).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx


@dataclass(slots=True)
class InterfaceModel:
    """A port on a node. Mirrors MASTER_SPEC §4 Interface."""

    id: str
    node_id: str
    name: str
    type: str = "eth"          # eth|sfp|sfp28|qsfp|gpon|wifi
    ips: list[str] = field(default_factory=list)
    mac: str | None = None
    speed: int = 1_000_000_000  # bits/s, default 1G
    mtu: int = 1500
    peer_link_id: str | None = None


@dataclass(slots=True)
class NodeModel:
    """A simulated device. Mirrors MASTER_SPEC §4 Node."""

    id: str
    name: str
    kind: str = "router"       # router|switch|host|ap|olt|firewall|server
    nos: str = "forgeos"       # forgeos|ios|junos|...
    mode: str = "sim"          # sim | emul
    interfaces: list[InterfaceModel] = field(default_factory=list)
    status: str = "up"         # up | down | provisioning

    def iface(self, iface_id: str) -> InterfaceModel | None:
        return next((i for i in self.interfaces if i.id == iface_id), None)


@dataclass(slots=True)
class LinkModel:
    """A bidirectional link between two interfaces. Mirrors §4 Link.

    The propagation characteristics here are what give the DES kernel its
    realism: ``delay`` is one-way propagation, serialization is derived from
    ``bandwidth`` and packet size, ``loss`` is a drop probability.
    """

    id: str
    a_iface: str
    b_iface: str
    type: str = "copper"       # copper|fiber|wireless|virtual
    bandwidth: int = 1_000_000_000  # bits/s
    delay: float = 0.001       # one-way propagation delay, seconds
    loss: float = 0.0          # drop probability [0.0, 1.0]
    mtu: int = 1500
    up: bool = True

    def serialization_delay(self, size_bytes: int) -> float:
        """Time to clock a frame of ``size_bytes`` onto this link."""
        if self.bandwidth <= 0:
            return 0.0
        return (size_bytes * 8) / self.bandwidth

    def transit_delay(self, size_bytes: int) -> float:
        """Total one-way delay = serialization + propagation."""
        return self.serialization_delay(size_bytes) + self.delay


class NetworkModel:
    """The full topology the engine runs against.

    Backed by a ``networkx.Graph`` for O(1) adjacency and reuse of graph
    algorithms (shortest path, connected components) by sim-mode protocol
    behaviours. Nodes/links/interfaces are also kept in flat dicts for fast id
    lookup on the hot path.
    """

    def __init__(self) -> None:
        self.graph = nx.Graph()
        self.nodes: dict[str, NodeModel] = {}
        self.links: dict[str, LinkModel] = {}
        self._iface_index: dict[str, InterfaceModel] = {}
        # iface_id -> link_id, for "which link does this port connect to?"
        self._iface_link: dict[str, str] = {}

    # ----- construction -------------------------------------------------
    def add_node(self, node: NodeModel) -> None:
        self.nodes[node.id] = node
        self.graph.add_node(node.id)
        for iface in node.interfaces:
            self._iface_index[iface.id] = iface

    def add_link(self, link: LinkModel) -> None:
        a = self._iface_index.get(link.a_iface)
        b = self._iface_index.get(link.b_iface)
        if a is None or b is None:
            raise ValueError(
                f"link {link.id} references unknown interface(s): "
                f"{link.a_iface}, {link.b_iface}"
            )
        self.links[link.id] = link
        self._iface_link[link.a_iface] = link.id
        self._iface_link[link.b_iface] = link.id
        self.graph.add_edge(a.node_id, b.node_id, link_id=link.id, weight=link.delay)

    # ----- queries ------------------------------------------------------
    def interface(self, iface_id: str) -> InterfaceModel | None:
        return self._iface_index.get(iface_id)

    def link_for_iface(self, iface_id: str) -> LinkModel | None:
        link_id = self._iface_link.get(iface_id)
        return self.links.get(link_id) if link_id else None

    def peer_interface(self, iface_id: str) -> InterfaceModel | None:
        """The interface on the other end of ``iface_id``'s link."""
        link = self.link_for_iface(iface_id)
        if not link:
            return None
        other = link.b_iface if link.a_iface == iface_id else link.a_iface
        return self._iface_index.get(other)

    def neighbors(self, node_id: str) -> list[str]:
        return list(self.graph.neighbors(node_id))

    def shortest_path(self, src: str, dst: str) -> list[str] | None:
        """Delay-weighted shortest path over *operational* links; None if
        disconnected.

        Used by sim-mode default forwarding when no protocol RIB is installed.
        Edges whose backing link is down are excluded so traffic reroutes around
        failures (and is dropped only when no healthy path remains) — otherwise
        downing a link had no routing effect.
        """
        def _edge_up(u: str, v: str) -> bool:
            link = self.links.get(self.graph[u][v].get("link_id"))
            return link is None or link.up

        graph = nx.subgraph_view(self.graph, filter_edge=_edge_up)
        try:
            return nx.shortest_path(graph, src, dst, weight="weight")
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None

    @property
    def stats(self) -> dict[str, int]:
        return {
            "nodes": len(self.nodes),
            "links": len(self.links),
            "interfaces": len(self._iface_index),
        }
