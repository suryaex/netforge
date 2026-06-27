/**
 * NetForge shared data model — mirrors MASTER_SPEC §4 exactly.
 * These types are the contract between frontend and the FastAPI backend.
 * Keep field names in sync with the backend Pydantic schemas.
 */

export type NodeKind =
  | 'router'
  | 'switch'
  | 'host'
  | 'ap'
  | 'olt'
  | 'firewall'
  | 'server'
  | 'cloud'; // bridge to a real host NIC / the internet (GNS3-style cloud)

export type Nos =
  | 'forgeos'
  | 'ios'
  | 'iosxr'
  | 'nxos'
  | 'junos'
  | 'eos'
  | 'routeros'
  | 'vyos'
  | 'sros'
  | 'frr'
  | 'vrp';

export type NodeMode = 'sim' | 'emul';
export type NodeStatus = 'stopped' | 'booting' | 'running' | 'degraded' | 'error';

export type IfaceType = 'eth' | 'sfp' | 'sfp28' | 'qsfp' | 'gpon' | 'wifi';
export type LinkType = 'copper' | 'fiber' | 'wireless' | 'virtual';
export type LinkStatus = 'up' | 'down' | 'admin_down' | 'unknown';
export type ConfigFormat = 'cli' | 'netconf' | 'yaml';

export interface Interface {
  id: string;
  node_id: string;
  name: string;
  type: IfaceType;
  ip: string[];
  mac: string;
  speed: number; // Mbps
  mtu: number;
  peer_link_id: string | null;
}

/** Where a cloud node attaches to the real world. Persisted in `intent.uplink`. */
export type UplinkMode = 'nat' | 'bridge';
export interface Uplink {
  adapter: string; // host NIC name, e.g. "eth0" / "Ethernet"
  mode: UplinkMode;
}

export interface NodeModel {
  id: string;
  project_id: string;
  name: string;
  kind: NodeKind;
  nos: Nos;
  mode: NodeMode;
  x: number;
  y: number;
  interfaces: Interface[];
  config_ref: string | null;
  status: NodeStatus;
  /** Extension bag (ForgeOS intent; cloud-node `uplink`). */
  intent?: Record<string, unknown> | null;
}

/** A detected host network adapter (GET /api/system/interfaces). */
export interface HostInterface {
  name: string;
  mac: string | null;
  ipv4: string[];
  ipv6: string[];
  is_up: boolean;
  speed_mbps: number;
  mtu: number;
  is_virtual: boolean;
  is_primary: boolean;
}

/** Internet reachability (GET /api/system/internet). */
export interface InternetStatus {
  online: boolean;
  latency_ms: number | null;
  via: string;
  source_ip: string | null;
}

export interface LinkModel {
  id: string;
  project_id: string;
  a_iface: string;
  b_iface: string;
  type: LinkType;
  bandwidth: number; // Mbps
  delay: number; // ms
  loss: number; // percent 0..100
  mtu: number;
  status?: LinkStatus;
}

export interface Project {
  id: string;
  name: string;
  description: string;
  version: string;
  topology_ref: string;
  created_at: string;
}

export interface ScenarioStep {
  id: string;
  description: string;
  action: string;
}

export interface Scenario {
  id: string;
  project_id: string;
  name: string;
  steps: ScenarioStep[];
  expected_outcomes: string[];
}

export interface ConfigArtifact {
  id: string;
  node_id: string;
  vendor: string;
  format: ConfigFormat;
  content: string;
  generated_at: string;
}

/** Full graph payload from GET /api/projects/{id}/topology and /ws/topology. */
export interface Topology {
  nodes: NodeModel[];
  links: LinkModel[];
}

/** Realtime events pushed over /ws/topology. */
export type TopologyEvent =
  | { type: 'snapshot'; topology: Topology }
  | { type: 'node.updated'; node: NodeModel }
  | { type: 'node.deleted'; node_id: string }
  | { type: 'node.status'; node_id: string; status: NodeStatus }
  | { type: 'link.updated'; link: LinkModel }
  | { type: 'link.deleted'; link_id: string }
  | { type: 'link.status'; link_id: string; status: LinkStatus }
  | { type: 'sim.tick'; t: number; metrics?: Record<string, number> };

/** Console frames over /ws/console/{node_id}. */
export type ConsoleEvent =
  | { type: 'banner'; node_id?: string; text: string }
  | { type: 'output'; node_id: string; data: string }
  | { type: 'prompt'; node_id: string; prompt: string }
  | { type: 'error'; node_id?: string; text: string }
  | { type: 'closed'; node_id: string; reason?: string };

/** Simulation lifecycle. */
export type SimState = 'idle' | 'running' | 'paused' | 'stepping';

export interface SimulateRequest {
  project_id: string;
  /** Corresponds to backend `realtime` bool — true = wall-clock realtime. */
  realtime?: boolean;
  seed?: number;
  horizon?: number;
}
