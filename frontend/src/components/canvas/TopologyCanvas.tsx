/**
 * TopologyCanvas — the heart of NetForge. React Flow canvas with:
 *  - drag-drop device creation from the palette (HTML5 DnD)
 *  - link creation by dragging between node handles
 *  - zoom/pan, minimap, snap grid
 *  - selection wired to the shared topology store
 *  - debounced position persistence to the backend (move flood control)
 *
 * Performance: store nodes live in Maps; we derive RF nodes/edges with a
 * memoized projection. `onlyRenderVisibleElements` keeps thousands of nodes
 * cheap. Node moves are committed locally immediately, pushed to the server
 * on drag-stop only (not on every frame).
 */
import { useCallback, useMemo, useRef } from 'react';
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  ConnectionMode,
  Controls,
  MiniMap,
  type Connection,
  type Edge,
  type Node,
  type NodeChange,
  type OnNodeDrag,
  type NodeMouseHandler,
  type ReactFlowInstance,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { DeviceNode, type DeviceNodeData } from './DeviceNode';
import { useTopologyStore } from '@/store/topologyStore';
import { useUiStore } from '@/store/uiStore';
import { nodesApi, linksApi } from '@/api/client';
import { deviceByKey } from '@/data/deviceCatalog';
import { linkStatusColors, nodeColors } from '@/theme/tokens';
import type { NodeModel } from '@/api/types';

const nodeTypes = { device: DeviceNode };

export function TopologyCanvas() {
  const rfRef = useRef<ReactFlowInstance<Node<DeviceNodeData>, Edge> | null>(null);
  const nodesMap = useTopologyStore((s) => s.nodes);
  const linksMap = useTopologyStore((s) => s.links);
  const selectedNodeId = useTopologyStore((s) => s.selectedNodeId);
  const moveNode = useTopologyStore((s) => s.moveNode);
  const upsertNode = useTopologyStore((s) => s.upsertNode);
  const upsertLink = useTopologyStore((s) => s.upsertLink);
  const select = useTopologyStore((s) => s.select);
  const projectId = useUiStore((s) => s.projectId);

  // Project store Maps -> React Flow nodes/edges (memoized by identity).
  const rfNodes: Node<DeviceNodeData>[] = useMemo(
    () =>
      Array.from(nodesMap.values()).map((n) => ({
        id: n.id,
        type: 'device',
        position: { x: n.x, y: n.y },
        selected: n.id === selectedNodeId,
        data: { name: n.name, kind: n.kind, nos: n.nos, mode: n.mode, status: n.status },
      })),
    [nodesMap, selectedNodeId],
  );

  const rfEdges: Edge[] = useMemo(
    () =>
      Array.from(linksMap.values()).map((l) => {
        const color = linkStatusColors[l.status ?? 'unknown'];
        return {
          id: l.id,
          source: ifaceNodeId(nodesMap, l.a_iface),
          target: ifaceNodeId(nodesMap, l.b_iface),
          animated: l.type === 'wireless',
          style: { stroke: color, strokeDasharray: l.type === 'fiber' ? '0' : '6 3' },
          data: { type: l.type, bandwidth: l.bandwidth },
        } as Edge;
      }),
    [linksMap, nodesMap],
  );

  /* --- Node drag: local move now, persist on drag-stop --------------------- */
  const onNodesChange = useCallback(
    (changes: NodeChange[]) => {
      for (const c of changes) {
        if (c.type === 'position' && c.position) {
          moveNode(c.id, c.position.x, c.position.y);
        }
      }
    },
    [moveNode],
  );

  const onNodeDragStop: OnNodeDrag<Node<DeviceNodeData>> = useCallback((_e, node) => {
    void nodesApi.move(node.id, node.position.x, node.position.y).catch(() => {});
  }, []);

  const onSelectionNode: NodeMouseHandler<Node<DeviceNodeData>> = useCallback(
    (_e, node) => select({ nodeId: node.id }),
    [select],
  );

  /* --- Link creation ------------------------------------------------------- */
  const onConnect = useCallback(
    (conn: Connection) => {
      if (!conn.source || !conn.target || !projectId) return;
      const aIface = firstFreeIface(nodesMap.get(conn.source));
      const bIface = firstFreeIface(nodesMap.get(conn.target));
      if (!aIface || !bIface) return;

      // Optimistic local edge; backend assigns the real link id.
      const tempId = `tmp-${conn.source}-${conn.target}-${Date.now()}`;
      upsertLink({
        id: tempId,
        project_id: projectId,
        a_iface: aIface,
        b_iface: bIface,
        type: 'copper',
        bandwidth: 1000,
        delay: 1,
        loss: 0,
        mtu: 1500,
        status: 'up',
      });
      void linksApi
        .create({ project_id: projectId, a_iface: aIface, b_iface: bIface, type: 'copper' })
        .then((real) => upsertLink(real))
        .catch(() => {});
    },
    [nodesMap, upsertLink, projectId],
  );

  /* --- Drag-drop device creation from the palette -------------------------- */
  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
  }, []);

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      if (!projectId) return;
      const key = e.dataTransfer.getData('application/netforge-device');
      const tpl = deviceByKey[key];
      if (!tpl || !rfRef.current) return;
      const pos = rfRef.current.screenToFlowPosition({ x: e.clientX, y: e.clientY });

      const tempId = `tmp-node-${Date.now()}`;
      const draft: NodeModel = {
        id: tempId,
        project_id: projectId,
        name: `${tpl.label.replace(/\s/g, '')}${nodesMap.size + 1}`,
        kind: tpl.kind,
        nos: tpl.defaultNos,
        mode: 'sim',
        x: pos.x,
        y: pos.y,
        interfaces: [],
        config_ref: null,
        status: 'stopped',
      };
      upsertNode(draft);
      select({ nodeId: tempId });
      void nodesApi
        .create({ project_id: projectId, name: draft.name, kind: draft.kind, nos: draft.nos, mode: 'sim', x: pos.x, y: pos.y })
        .then((real) => upsertNode(real))
        .catch(() => {});
    },
    [nodesMap.size, upsertNode, select, projectId],
  );

  return (
    <div className="h-full w-full" onDragOver={onDragOver} onDrop={onDrop}>
      <ReactFlow
        onInit={(inst) => (rfRef.current = inst)}
        nodes={rfNodes}
        edges={rfEdges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onNodeDragStop={onNodeDragStop}
        onNodeClick={onSelectionNode}
        onConnect={onConnect}
        onPaneClick={() => select({ nodeId: null, linkId: null })}
        onEdgeClick={(_e, edge) => select({ linkId: edge.id })}
        connectionMode={ConnectionMode.Loose}
        fitView
        snapToGrid
        snapGrid={[16, 16]}
        minZoom={0.2}
        maxZoom={2.5}
        onlyRenderVisibleElements
        proOptions={{ hideAttribution: true }}
        defaultEdgeOptions={{ type: 'smoothstep' }}
      >
        <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="rgba(255,255,255,0.08)" />
        <Controls className="!border-white/10 !bg-white/5 backdrop-blur" />
        <MiniMap
          pannable
          zoomable
          nodeColor={(n) => nodeColors[(n.data as DeviceNodeData).kind] ?? '#888'}
          className="!rounded-md !border !border-white/10 !bg-black/30"
        />
      </ReactFlow>
    </div>
  );
}

/* ----------------------------- helpers ----------------------------------- */
function ifaceNodeId(nodes: Map<string, NodeModel>, ifaceId: string): string {
  for (const n of nodes.values()) {
    if (n.interfaces.some((i) => i.id === ifaceId)) return n.id;
  }
  // Fallback for optimistic temp links keyed by node id directly.
  return ifaceId;
}

function firstFreeIface(node?: NodeModel): string | null {
  if (!node) return null;
  const free = node.interfaces.find((i) => i.peer_link_id == null);
  // If no modeled interfaces yet (fresh node), use node id as a stand-in so the
  // optimistic edge renders; backend resolves the real interface on create.
  return free?.id ?? node.id;
}
