/**
 * Topology store — the authoritative client-side graph model.
 * Server is the source of truth; this store holds the optimistic local copy
 * that the canvas renders, and reconciles against /ws/topology events.
 *
 * We keep nodes/links in normalized Maps for O(1) updates (thousands of nodes
 * is a design target, so array scans on every tick are avoided).
 */
import { create } from 'zustand';
import type { LinkModel, NodeModel, Topology, TopologyEvent } from '@/api/types';

interface TopologyState {
  nodes: Map<string, NodeModel>;
  links: Map<string, LinkModel>;
  selectedNodeId: string | null;
  selectedLinkId: string | null;
  dirty: boolean; // unsaved local edits

  // selectors
  nodeList: () => NodeModel[];
  linkList: () => LinkModel[];
  selectedNode: () => NodeModel | null;

  // mutations (local/optimistic)
  loadSnapshot: (topology: Topology) => void;
  upsertNode: (node: NodeModel) => void;
  upsertLink: (link: LinkModel) => void;
  removeNode: (id: string) => void;
  removeLink: (id: string) => void;
  moveNode: (id: string, x: number, y: number) => void;
  select: (sel: { nodeId?: string | null; linkId?: string | null }) => void;

  /** Apply a realtime event from the server channel. */
  applyEvent: (ev: TopologyEvent) => void;
}

export const useTopologyStore = create<TopologyState>((set, get) => ({
  nodes: new Map(),
  links: new Map(),
  selectedNodeId: null,
  selectedLinkId: null,
  dirty: false,

  nodeList: () => Array.from(get().nodes.values()),
  linkList: () => Array.from(get().links.values()),
  selectedNode: () => {
    const id = get().selectedNodeId;
    return id ? (get().nodes.get(id) ?? null) : null;
  },

  loadSnapshot: (topology) =>
    set(() => ({
      nodes: new Map(topology.nodes.map((n) => [n.id, n])),
      links: new Map(topology.links.map((l) => [l.id, l])),
      dirty: false,
    })),

  upsertNode: (node) =>
    set((s) => {
      const nodes = new Map(s.nodes);
      nodes.set(node.id, node);
      return { nodes, dirty: true };
    }),

  upsertLink: (link) =>
    set((s) => {
      const links = new Map(s.links);
      links.set(link.id, link);
      return { links, dirty: true };
    }),

  removeNode: (id) =>
    set((s) => {
      const nodes = new Map(s.nodes);
      nodes.delete(id);
      // cascade-remove attached links
      const links = new Map(s.links);
      const node = s.nodes.get(id);
      const ifaceIds = new Set(node?.interfaces.map((i) => i.id) ?? []);
      for (const [lid, l] of links) {
        if (ifaceIds.has(l.a_iface) || ifaceIds.has(l.b_iface)) links.delete(lid);
      }
      return {
        nodes,
        links,
        dirty: true,
        selectedNodeId: s.selectedNodeId === id ? null : s.selectedNodeId,
      };
    }),

  removeLink: (id) =>
    set((s) => {
      const links = new Map(s.links);
      links.delete(id);
      return { links, dirty: true, selectedLinkId: s.selectedLinkId === id ? null : s.selectedLinkId };
    }),

  moveNode: (id, x, y) =>
    set((s) => {
      const node = s.nodes.get(id);
      if (!node) return {};
      const nodes = new Map(s.nodes);
      nodes.set(id, { ...node, x, y });
      return { nodes, dirty: true };
    }),

  select: ({ nodeId, linkId }) =>
    set(() => ({
      selectedNodeId: nodeId ?? null,
      selectedLinkId: linkId ?? null,
    })),

  applyEvent: (ev) =>
    set((s) => {
      switch (ev.type) {
        case 'snapshot':
          return {
            nodes: new Map(ev.topology.nodes.map((n) => [n.id, n])),
            links: new Map(ev.topology.links.map((l) => [l.id, l])),
          };
        case 'node.updated': {
          const nodes = new Map(s.nodes);
          nodes.set(ev.node.id, ev.node);
          return { nodes };
        }
        case 'node.deleted': {
          if (!s.nodes.has(ev.node_id)) return {};
          const nodes = new Map(s.nodes);
          const node = nodes.get(ev.node_id);
          nodes.delete(ev.node_id);
          // cascade-remove links attached to this node's interfaces
          const links = new Map(s.links);
          const ifaceIds = new Set(node?.interfaces.map((i) => i.id) ?? []);
          for (const [lid, l] of links) {
            if (ifaceIds.has(l.a_iface) || ifaceIds.has(l.b_iface)) links.delete(lid);
          }
          return {
            nodes,
            links,
            selectedNodeId: s.selectedNodeId === ev.node_id ? null : s.selectedNodeId,
          };
        }
        case 'node.status': {
          const node = s.nodes.get(ev.node_id);
          if (!node) return {};
          const nodes = new Map(s.nodes);
          nodes.set(ev.node_id, { ...node, status: ev.status });
          return { nodes };
        }
        case 'link.updated': {
          const links = new Map(s.links);
          links.set(ev.link.id, ev.link);
          return { links };
        }
        case 'link.deleted': {
          if (!s.links.has(ev.link_id)) return {};
          const links = new Map(s.links);
          links.delete(ev.link_id);
          return {
            links,
            selectedLinkId: s.selectedLinkId === ev.link_id ? null : s.selectedLinkId,
          };
        }
        case 'link.status': {
          const link = s.links.get(ev.link_id);
          if (!link) return {};
          const links = new Map(s.links);
          links.set(ev.link_id, { ...link, status: ev.status });
          return { links };
        }
        default:
          return {};
      }
    }),
}));
