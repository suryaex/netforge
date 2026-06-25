/**
 * REST client for the NetForge FastAPI backend (MASTER_SPEC §4).
 * Thin axios wrapper: single base instance, JSON, error normalization, and
 * typed resource functions. The dev server proxies `/api` to the backend, so
 * we use a same-origin relative baseURL by default.
 */
import axios, { AxiosError } from 'axios';
import type {
  ConfigArtifact,
  LinkModel,
  NodeModel,
  Project,
  Scenario,
  SimulateRequest,
  Topology,
} from './types';

export const API_BASE = import.meta.env.VITE_API_BASE ?? '/api';

export const http = axios.create({
  baseURL: API_BASE,
  headers: { 'Content-Type': 'application/json' },
  timeout: 20_000,
});

/** Normalized error shape surfaced to UI (error states must be first-class). */
export interface ApiError {
  status: number;
  message: string;
  detail?: unknown;
}

http.interceptors.response.use(
  (res) => res,
  (err: AxiosError<{ detail?: unknown }>) => {
    const apiError: ApiError = {
      status: err.response?.status ?? 0,
      message:
        (typeof err.response?.data?.detail === 'string' && err.response.data.detail) ||
        err.message ||
        'Network error',
      detail: err.response?.data?.detail,
    };
    return Promise.reject(apiError);
  },
);

/* ----------------------------- Projects ---------------------------------- */
export const projectsApi = {
  list: () => http.get<Project[]>('/projects').then((r) => r.data),
  get: (id: string) => http.get<Project>(`/projects/${id}`).then((r) => r.data),
  create: (body: Partial<Project>) => http.post<Project>('/projects', body).then((r) => r.data),
  topology: (id: string) =>
    http.get<Topology>(`/projects/${id}/topology`).then((r) => r.data),
};

/* ------------------------------- Nodes ----------------------------------- */
export const nodesApi = {
  create: (body: Partial<NodeModel>) => http.post<NodeModel>('/nodes', body).then((r) => r.data),
  update: (id: string, patch: Partial<NodeModel>) =>
    http.patch<NodeModel>(`/nodes/${id}`, patch).then((r) => r.data),
  remove: (id: string) => http.delete(`/nodes/${id}`).then(() => undefined),
  /** Move is sent debounced from the canvas to avoid request floods. */
  move: (id: string, x: number, y: number) =>
    http.patch<NodeModel>(`/nodes/${id}`, { x, y }).then((r) => r.data),
};

/* ------------------------------- Links ----------------------------------- */
export const linksApi = {
  create: (body: Partial<LinkModel>) => http.post<LinkModel>('/links', body).then((r) => r.data),
  update: (id: string, patch: Partial<LinkModel>) =>
    http.patch<LinkModel>(`/links/${id}`, patch).then((r) => r.data),
  remove: (id: string) => http.delete(`/links/${id}`).then(() => undefined),
};

/* ----------------------------- Scenarios --------------------------------- */
export const scenariosApi = {
  list: (projectId: string) =>
    http.get<Scenario[]>('/scenarios', { params: { project_id: projectId } }).then((r) => r.data),
};

/* ----------------------------- Simulation -------------------------------- */
export const simApi = {
  start: (body: SimulateRequest) => http.post('/simulate', body).then((r) => r.data),
  pause: (projectId: string) => http.post(`/simulate/${projectId}/pause`).then((r) => r.data),
  resume: (projectId: string) => http.post(`/simulate/${projectId}/resume`).then((r) => r.data),
  step: (projectId: string) => http.post(`/simulate/${projectId}/step`).then((r) => r.data),
  stop: (projectId: string) => http.post(`/simulate/${projectId}/stop`).then((r) => r.data),
};

/* ----------------------------- Config-gen -------------------------------- */
export const configsApi = {
  generate: (nodeId: string, vendor?: string) =>
    http
      .post<ConfigArtifact>('/configs/generate', { node_id: nodeId, vendor })
      .then((r) => r.data),
  forNode: (nodeId: string) =>
    http.get<ConfigArtifact[]>('/configs', { params: { node_id: nodeId } }).then((r) => r.data),
};

/* ----------------------------- Self-update ------------------------------- */
export interface UpdateCheck {
  current: string;
  latest: string | null;
  update_available: boolean;
  notes?: string;
  url?: string;
  published_at?: string;
  checked_at: number;
  can_apply?: boolean;
  error?: string;
}
export interface UpdateStatus {
  state:
    | 'idle'
    | 'queued'
    | 'updating'
    | 'rebuilding'
    | 'restarting'
    | 'done'
    | 'up-to-date'
    | 'error';
  message?: string;
  at?: number;
}
export const updateApi = {
  check: () => http.get<UpdateCheck>('/update/check').then((r) => r.data),
  status: () => http.get<UpdateStatus>('/update/status').then((r) => r.data),
  apply: (token: string) =>
    http
      .post<UpdateStatus>('/update/apply', null, { headers: { 'X-Update-Token': token } })
      .then((r) => r.data),
};
