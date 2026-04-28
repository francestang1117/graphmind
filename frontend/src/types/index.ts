// Shared API shapes for modules that are being wired in gradually.
export interface UploadResponse {
  filename: string;
  original_filename: string;
  size: number;
  file_type: string;
  file_hash: string;
  status: string;
  message: string;
  deduplicated: boolean;
}

export interface GraphNode {
  id: string;
  label: string;
  type: string;
  size?: number;
  sources?: string[];
}

export interface GraphEdge {
  source: string;
  target: string;
  type: string;
  confidence: number;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: [string, string][];
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

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  sources?: string[];
}

export interface ChatResponse {
  answer: string;
  sources: Array<string | { document: string }>;
  conversation_id: string;
}

export interface VideoJob {
  job_id: string;
  status: "queued" | "running" | "done" | "error";
}

export interface VideoProgress {
  state: string;
  pct: number;
  step: string;
  result?: Record<string, unknown>;
  error?: string;
}

export interface KnowledgeGap {
  label: string;
  type: string;
  severity: number;
  in_degree: number;
  suggestion: string;
}

export interface GapSummary {
  total_gaps: number;
  by_type: Record<string, number>;
  top_gaps: KnowledgeGap[];
  search_queries: string[];
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface User {
  id: string;
  email: string;
  name: string;
  created_at: string;
}
