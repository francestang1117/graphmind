import axios from "axios";
import type { FileInfo } from "../stores/appStore";

const API_BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

// Implemented: document upload/list/delete/parsed APIs plus future graph/search/chat wrappers.
const http = axios.create({ baseURL: `${API_BASE}/api/v1`, timeout: 30_000 });

export interface GraphNode {
  id: string;
  label: string;
  type: string;
  size: number;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: Array<[string, string]>;
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

export interface ParsedMarkdownSummary {
  filename: string;
  title: string;
  headers_count: number;
  sections_count: number;
  links_count: number;
  images_count: number;
  code_blocks_count: number;
  word_count: number;
  reading_time: number;
  has_code: boolean;
  languages: string[];
}

export const checkHealth = () =>
  axios.get(`${API_BASE}/health`, { timeout: 2000 }).then((r) => r.data);

export const uploadDocument = (
  file: File,
  onProgress?: (n: number) => void,
) => {
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

export const listDocuments = (): Promise<FileInfo[]> =>
  http.get("/documents/").then((r) => r.data.files ?? []);

export const deleteDocument = (filename: string) =>
  http.delete(`/documents/${encodeURIComponent(filename)}`);

export const getParsedDocument = (filename: string): Promise<ParsedMarkdownSummary> =>
  http.get(`/documents/${encodeURIComponent(filename)}/parsed`).then((r) => r.data);

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
  const raw = data as Partial<GraphData> | undefined;
  return {
    nodes: raw?.nodes ?? [],
    edges: raw?.edges ?? [],
    stats: raw?.stats ?? {
      total_nodes: raw?.nodes?.length ?? 0,
      total_edges: raw?.edges?.length ?? 0,
      node_types: {},
    },
  };
}

export default http;
