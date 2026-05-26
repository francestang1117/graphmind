import axios from "axios";
import type { FileInfo } from "../stores/appStore";

const API_BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

const http = axios.create({ baseURL: `${API_BASE}/api/v1`, timeout: 30_000 });

export interface UploadResponse {
  filename: string;
  original_filename: string;
  file_size: number;
  file_type: string;
  file_hash: string;
  status: string;
  job_id?: string | null;
}

export interface JobProgress {
  state: "PENDING" | "PROGRESS" | "SUCCESS" | "FAILURE" | "REVOKED" | "ERROR" | string;
  pct: number;
  step: string;
  result?: Record<string, unknown>;
  error?: string;
}

export interface GraphNode {
  id: string;
  label: string;
  type: string;
  size: number;
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

export function watchJobProgress(
  jobId: string,
  onProgress: (progress: JobProgress) => void,
) {
  return new Promise<JobProgress>((resolve, reject) => {
    const ws = new WebSocket(`${toWsBase(API_BASE)}/ws/jobs/${encodeURIComponent(jobId)}`);

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

export const listDocuments = (): Promise<FileInfo[]> =>
  http.get("/documents/").then((r) => r.data.files ?? []);

export const deleteDocument = (filename: string) =>
  http.delete(`/documents/${encodeURIComponent(filename)}`);

export const getParsedDocument = (filename: string): Promise<ParsedDocumentSummary> =>
  http.get(`/documents/${encodeURIComponent(filename)}/parsed`).then((r) => r.data);

export const getDocumentOpenUrl = (filename: string) =>
  `${API_BASE}/api/v1/documents/${encodeURIComponent(filename)}/open`;

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

function toWsBase(baseUrl: string) {
  const url = new URL(baseUrl);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString().replace(/\/$/, "");
}
