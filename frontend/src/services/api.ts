import axios from "axios";
import type { FileInfo } from "../stores/appStore";
import type { AuthProviders, TokenPair, User } from "../types";
import {
  clearTokens,
  getAccessToken,
  saveAccessToken,
} from "./authSession";

const API_BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
export const AUTH_REQUIRED_EVENT = "graphmind:auth-required";

const http = axios.create({
  baseURL: `${API_BASE}/api/v1`,
  timeout: 30_000,
  withCredentials: true,
});

http.interceptors.request.use((config) => {
  const token = getAccessToken();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

let refreshRequest: Promise<string> | null = null;

function notifyAuthRequired(url?: string) {
  // A guest check on startup is normal; a private workspace request is not.
  if (url?.includes("/auth/me")) return;
  window.dispatchEvent(new Event(AUTH_REQUIRED_EVENT));
}

http.interceptors.response.use(undefined, async (error) => {
  const request = error.config as (typeof error.config & { _retried?: boolean }) | undefined;
  if (error.response?.status !== 401 || !request) {
    return Promise.reject(error);
  }
  if (request._retried) {
    notifyAuthRequired(request.url);
    return Promise.reject(error);
  }

  request._retried = true;
  refreshRequest ??= axios
    .post<{ access_token: string }>(
      `${API_BASE}/api/v1/auth/refresh`,
      {},
      { withCredentials: true },
    )
    .then(({ data }) => {
      saveAccessToken(data.access_token);
      return data.access_token;
    })
    .finally(() => {
      refreshRequest = null;
    });

  try {
    const token = await refreshRequest;
    request.headers.Authorization = `Bearer ${token}`;
    return http(request);
  } catch (refreshError) {
    clearTokens();
    notifyAuthRequired(request.url);
    return Promise.reject(refreshError);
  }
});

export function isAuthenticationError(error: unknown) {
  return axios.isAxiosError(error) && error.response?.status === 401;
}

export interface UploadResponse {
  filename: string;
  original_filename: string;
  file_size: number;
  file_type: string;
  file_hash: string;
  status: string;
  job_id?: string | null;
  document_id?: string | null;
  workspace_id?: string | null;
  document_kind?: string | null;
}

export interface MedicalInsightEvidence {
  id: string;
  evidence_id: string;
  finding_id: string;
  chunk_id: string;
  section_id?: string | null;
  section_type?: string | null;
  section_title?: string | null;
  page_start?: number | null;
  page_end?: number | null;
  quote: string;
  character_start?: number | null;
  character_end?: number | null;
}

export interface MedicalInsightFinding {
  id: string;
  statement: string;
  plain_explanation: string;
  evidence_ids: string[];
  evidence_level: string;
  interpretation_type: "direct_statement" | "summary" | "inference" | "uncertain" | string;
}

export interface MedicalInsightAttribute {
  value: string;
  support_status: "supported" | "partially_supported" | "not_reported" | "uncertain" | string;
  evidence_ids: string[];
}

export interface MedicalInsightReport {
  schema_version: string;
  document_kind: string;
  language: string;
  overview: {
    title: string;
    summary: string;
    study_type: string;
    evidence_ids: string[];
  };
  study_methods?: {
    design: MedicalInsightAttribute;
    population: MedicalInsightAttribute;
    human_animal_in_vitro: MedicalInsightAttribute;
    sample_size: MedicalInsightAttribute;
    comparator: MedicalInsightAttribute;
  };
  key_findings: MedicalInsightFinding[];
  limitations: MedicalInsightFinding[];
  medical_terms: Array<{
    term: string;
    explanation: string;
    evidence_ids: string[];
  }>;
  what_it_means: MedicalInsightFinding[];
  what_it_does_not_mean: MedicalInsightFinding[];
  applicability?: MedicalInsightFinding[];
  future_research?: MedicalInsightFinding[];
  questions_for_professional: string[];
  coverage?: {
    complete: boolean;
    selected_chunks: number;
    total_chunks: number;
    selected_tokens: number;
    max_input_tokens: number;
    included_sections: string[];
    omitted_sections: string[];
  };
  warnings: string[];
}

export interface MedicalInsightRun {
  run_id: string;
  document_id: string;
  workspace_id: string;
  status: "queued" | "running" | "succeeded" | "failed" | string;
  source_hash: string;
  parsed_source_hash?: string;
  provider: string;
  model_name: string;
  prompt_version: string;
  schema_version: string;
  redact_pii?: boolean;
  max_input_tokens?: number;
  timeout_seconds?: number;
  max_output_tokens?: number;
  provider_retry_count?: number;
  external_processing_confirmed_at?: string;
  attempt_count?: number;
  last_heartbeat_at?: string;
  lease_expires_at?: string;
  error_code?: string;
  error_message?: string;
  is_current?: boolean;
  outdated?: boolean;
  created_at?: string;
  started_at?: string;
  completed_at?: string;
  updated_at?: string;
  report?: MedicalInsightReport;
  citation_coverage?: number;
  validation_status?: string;
  warnings?: string[];
  evidence?: MedicalInsightEvidence[];
}

export interface MedicalInsightConfig {
  enabled: boolean;
  configured: boolean;
  provider: string;
  model_name: string;
  external_processing: boolean;
  requires_confirmation: boolean;
  sends_selected_excerpts: boolean;
  redact_pii: boolean;
  config_fingerprint: string;
}

export interface JobProgress {
  state: "PENDING" | "PROGRESS" | "SUCCESS" | "FAILURE" | "REVOKED" | "ERROR" | string;
  pct: number;
  step: string;
  result?: Record<string, unknown>;
  error?: string;
  job?: JobHistoryItem;
}

export interface JobHistoryItem {
  job_id: string;
  document_id: string;
  original_filename: string;
  status: string;
  step: string;
  progress: number;
  error?: string;
  created_at?: string;
  updated_at?: string;
  finished_at?: string | null;
}

export interface WebSocketTicketResponse {
  ticket: string;
  expires_in: number;
}

export interface GraphNode {
  id: string;
  label: string;
  type: string;
  size: number;
  importance?: number;
  connections?: number;
}

export interface GraphEdge {
  source: string;
  target: string;
  type?: string;
  weight?: number;
  confidence?: number;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
  stats: {
    total_nodes: number;
    total_edges: number;
    node_types: Record<string, number>;
  };
}

export interface SearchResult {
  title: string;
  type: string;
  score: number;
  excerpt: string;
  source: string;
  tags?: string[];
}

export interface ParsedDocumentSummary {
  filename: string;
  title: string;
  format: string;
  headers_count: number;
  sections_count: number;
  chunks_count: number;
  links_count: number;
  images_count: number;
  list_items_count: number;
  code_blocks_count: number;
  tables_count: number;
  imports_count: number;
  functions_count: number;
  classes_count: number;
  entities_count: number;
  pages_count: number;
  paragraphs_count: number;
  comments_count: number;
  inherited_styles_count: number;
  word_count: number;
  reading_time: number;
  has_code: boolean;
  languages: string[];
  imports: string[];
  functions: string[];
  classes: string[];
  entities: Array<{ type?: string; text?: string }>;
}

export const checkHealth = () =>
  axios.get(`${API_BASE}/health`, { timeout: 2000 }).then((r) => r.data);

export const registerAccount = (email: string, password: string, name: string) =>
  http
    .post<TokenPair>("/auth/register", { email, password, name })
    .then((r) => r.data);

export const loginAccount = (email: string, password: string) => {
  const form = new URLSearchParams({ username: email, password });
  return http
    .post<TokenPair>("/auth/login", form, {
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
    })
    .then((r) => r.data);
};

export const getCurrentUser = (): Promise<User> =>
  http.get("/auth/me").then((r) => r.data);

export const logoutAccount = () => http.post("/auth/logout", {});

export const getAuthProviders = (): Promise<AuthProviders> =>
  http.get("/auth/providers").then((r) => r.data);

export const getGithubLoginUrl = (returnOrigin: string) =>
  `${API_BASE}/api/v1/auth/github/start?return_origin=${encodeURIComponent(returnOrigin)}`;

export const exchangeOAuthCode = (code: string) =>
  http.post<{ access_token: string }>("/auth/oauth/exchange", { code }).then((r) => r.data);

export const isApiOrigin = (origin: string) => origin === new URL(API_BASE).origin;

export const uploadDocument = (
  file: File,
  onProgress?: (n: number) => void,
): Promise<UploadResponse> => {
  const form = new FormData();
  form.append("file", file);
  return http
    .post("/documents/upload", form, {
      headers: { "Content-Type": "multipart/form-data" },
      onUploadProgress: (event) => {
        if (event.total) onProgress?.(Math.round((event.loaded * 100) / event.total));
      },
    })
    .then((r) => r.data);
};

export const createJobWebSocketTicket = (jobId: string): Promise<WebSocketTicketResponse> =>
  http
    .post<WebSocketTicketResponse>(`/jobs/${encodeURIComponent(jobId)}/ws-ticket`)
    .then((r) => r.data);

export async function watchJobProgress(
  jobId: string,
  onProgress: (progress: JobProgress) => void,
) {
  const { ticket } = await createJobWebSocketTicket(jobId);

  return new Promise<JobProgress>((resolve, reject) => {
    const ws = new WebSocket(
      `${toWsBase(API_BASE)}/ws/jobs/${encodeURIComponent(jobId)}?ticket=${encodeURIComponent(ticket)}`,
    );

    ws.onmessage = (event) => {
      const progress = JSON.parse(event.data) as JobProgress;
      onProgress(progress);

      if (progress.state === "SUCCESS") {
        ws.close();
        resolve(progress);
      }

      if (["FAILURE", "REVOKED", "ERROR"].includes(progress.state)) {
        ws.close();
        reject(new Error(progress.error || progress.step || "Processing failed"));
      }
    };

    ws.onerror = () => {
      reject(new Error("Could not connect to the processing job."));
    };
  });
}

export const getJob = (jobId: string): Promise<JobProgress> =>
  http.get(`/jobs/${encodeURIComponent(jobId)}`).then((r) => r.data);

export const cancelJob = (jobId: string): Promise<JobProgress> =>
  http.post(`/jobs/${encodeURIComponent(jobId)}/cancel`).then((r) => r.data);

export const listJobs = (limit = 50): Promise<JobHistoryItem[]> =>
  http.get("/jobs/", { params: { limit } }).then((r) => r.data.jobs ?? []);

export const listDocuments = (workspaceId?: string | null): Promise<FileInfo[]> =>
  http.get("/documents/", workspaceParams(workspaceId)).then((r) => r.data.files ?? []);

export const deleteDocument = (filename: string, workspaceId?: string | null) =>
  http.delete(`/documents/${encodeURIComponent(filename)}`, workspaceParams(workspaceId));

export const getParsedDocument = (
  filename: string,
  workspaceId?: string | null,
): Promise<ParsedDocumentSummary> =>
  http
    .get(`/documents/${encodeURIComponent(filename)}/parsed`, workspaceParams(workspaceId))
    .then((r) => r.data);

export const getDocumentOpenUrl = (filename: string, workspaceId?: string | null) => {
  const query = workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : "";
  return `${API_BASE}/api/v1/documents/${encodeURIComponent(filename)}/open${query}`;
};

export const startMedicalInsights = (
  documentId: string,
  workspaceId?: string | null,
  externalProcessingConfirmed = false,
  externalProcessingConfigFingerprint?: string,
): Promise<MedicalInsightRun> =>
  http
    .post<MedicalInsightRun>(
      `/documents/${encodeURIComponent(documentId)}/medical-insights`,
      {
        external_processing_confirmed: externalProcessingConfirmed,
        external_processing_config_fingerprint: externalProcessingConfigFingerprint,
      },
      workspaceParams(workspaceId),
    )
    .then((r) => r.data);

export const reanalyzeMedicalInsights = (
  documentId: string,
  workspaceId?: string | null,
  externalProcessingConfirmed = false,
  externalProcessingConfigFingerprint?: string,
): Promise<MedicalInsightRun> =>
  http
    .post<MedicalInsightRun>(
      `/documents/${encodeURIComponent(documentId)}/medical-insights/reanalyze`,
      {
        external_processing_confirmed: externalProcessingConfirmed,
        external_processing_config_fingerprint: externalProcessingConfigFingerprint,
      },
      workspaceParams(workspaceId),
    )
    .then((r) => r.data);

export const getMedicalInsightConfig = (): Promise<MedicalInsightConfig> =>
  http.get<MedicalInsightConfig>("/medical-insights/config").then((r) => r.data);

export const getMedicalInsightRun = (
  runId: string,
  workspaceId?: string | null,
): Promise<MedicalInsightRun> =>
  http
    .get<MedicalInsightRun>(
      `/medical-analysis-runs/${encodeURIComponent(runId)}`,
      workspaceParams(workspaceId),
    )
    .then((r) => r.data);

export const getLatestMedicalInsights = (
  documentId: string,
  workspaceId?: string | null,
): Promise<MedicalInsightRun> =>
  http
    .get<MedicalInsightRun>(
      `/documents/${encodeURIComponent(documentId)}/medical-insights/latest`,
      workspaceParams(workspaceId),
    )
    .then((r) => r.data);

export const getCurrentMedicalInsights = (
  documentId: string,
  workspaceId?: string | null,
): Promise<MedicalInsightRun> =>
  http
    .get<MedicalInsightRun>(
      `/documents/${encodeURIComponent(documentId)}/medical-insights/current`,
      workspaceParams(workspaceId),
    )
    .then((r) => r.data);

export const fetchGraph = (): Promise<GraphData> =>
  http.get("/graph").then((r) => normalizeGraph(r.data));

export const fetchGraphStats = () =>
  http.get("/graph/stats").then((r) => r.data);

export const fetchNodeDetail = (id: string) =>
  http.get(`/graph/nodes/${encodeURIComponent(id)}`).then((r) => r.data);

export const semanticSearch = (
  query: string,
  limit = 10,
  searchType = "hybrid",
): Promise<SearchResult[]> =>
  http
    .post("/search", { query, limit, search_type: searchType })
    .then((r) => r.data.results ?? []);

export const sendChatMessage = (
  message: string,
  conversationId?: string | null,
) =>
  http
    .post("/chat", { message, conversation_id: conversationId })
    .then((r) => r.data);

function normalizeGraph(data: unknown): GraphData {
  const raw = data as (Partial<GraphData> & { edge_details?: GraphEdge[] }) | undefined;
  const rawEdges = raw?.edge_details ?? raw?.edges ?? [];
  return {
    nodes: raw?.nodes ?? [],
    edges: rawEdges.map((edge) => {
      if (Array.isArray(edge)) {
        return { source: edge[0], target: edge[1] };
      }
      return edge;
    }),
    stats: raw?.stats ?? {
      total_nodes: raw?.nodes?.length ?? 0,
      total_edges: raw?.edges?.length ?? 0,
      node_types: {},
    },
  };
}

export default http;

function workspaceParams(workspaceId?: string | null) {
  return workspaceId ? { params: { workspace_id: workspaceId } } : undefined;
}

function toWsBase(baseUrl: string) {
  const url = new URL(baseUrl);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString().replace(/\/$/, "");
}
