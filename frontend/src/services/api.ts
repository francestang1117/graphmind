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

export interface WorkspaceInfo {
  id: string;
  user_id: string;
  name: string;
  research_question: string;
  domain: string;
  status: string;
  created_at: string;
  updated_at: string;
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
  missing_reason?: "not_reported_in_source" | "not_extracted_from_analyzed_text" | "source_unreadable" | string;
}

export type QuestionSuggestionCategory =
  | "clarify_finding"
  | "applicability"
  | "study_limitation"
  | "monitoring_discussion"
  | "research_option";

export type QuestionSuggestionTopic =
  | "study_population"
  | "study_design"
  | "reported_result"
  | "term_clarification"
  | "study_limitation"
  | "monitoring"
  | "future_research";

export type QuestionSourceKind =
  | "study_methods"
  | "key_findings"
  | "medical_terms"
  | "limitations"
  | "future_research";

export interface MedicalQuestionSuggestion {
  id: string;
  question: string;
  rationale: string;
  category: QuestionSuggestionCategory;
  topic?: QuestionSuggestionTopic;
  source_kind?: QuestionSourceKind;
  source_id?: string;
  evidence_ids: string[];
  interpretation_type:
    | "direct_statement"
    | "summary"
    | "inference"
    | "uncertain";
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
  question_suggestions?: MedicalQuestionSuggestion[];
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

export type DiseaseProfileSection =
  | "key_findings"
  | "study_methods"
  | "limitations"
  | "what_it_means"
  | "what_it_does_not_mean"
  | "applicability"
  | "future_research"
  | "medical_terms"
  | "clinician_questions"
  | "external_studies";

export interface DiseaseProfileSource {
  source_type: "document_evidence" | "external_article";
  evidence_id?: string | null;
  document_id?: string | null;
  document_title: string;
  document_date: string;
  analysis_run_id?: string | null;
  parsed_source_hash: string;
  section_type: string;
  section_title: string;
  page_start?: number | null;
  page_end?: number | null;
  quote: string;
  source: string;
  external_id: string;
  source_url: string;
  retraction_status: string;
  flagged: boolean;
  warnings: string[];
}

export interface DiseaseProfileItem {
  id: string;
  item_type: "finding" | "attribute" | "term" | "question" | "article";
  section: DiseaseProfileSection;
  document_id?: string | null;
  document_ids: string[];
  document_title: string;
  document_titles: string[];
  related_document_count: number;
  related_documents_truncated: boolean;
  document_kind: string;
  document_date: string;
  analysis_run_id?: string | null;
  parsed_source_hash: string;
  source_status: "current" | "outdated" | "unavailable";
  title: string;
  text: string;
  explanation: string;
  value: string;
  support_status: string;
  term: string;
  question: string;
  rationale: string;
  category: string;
  topic: string;
  source_kind: string;
  source_id: string;
  evidence_ids: string[];
  evidence: DiseaseProfileSource[];
  evidence_truncated: boolean;
  source: string;
  external_id: string;
  doi?: string | null;
  pmcid?: string | null;
  journal: string;
  publication_date?: string | null;
  publication_year?: number | null;
  publication_types: string[];
  source_url: string;
  retraction_status: string;
  flagged: boolean;
  warnings: string[];
  relevance_score?: number | null;
  match_specificity: string;
}

export interface DiseaseProfileDocument {
  document_id: string;
  title: string;
  document_kind: string;
  language: string;
  document_date: string;
  parsed_source_hash: string;
  current_analysis_run_id: string | null;
  source_status: "current" | "outdated" | "unavailable";
  warnings: string[];
}

export interface DiseaseProfileStats {
  document_count: number;
  research_paper_count: number;
  guideline_count: number;
  other_medical_document_count: number;
  valid_analysis_count: number;
  expired_analysis_count: number;
  external_article_count: number;
  flagged_article_count: number;
  comparator_reported_count: number;
  comparator_not_reported_count: number;
  human_study_count: number;
  animal_study_count: number;
  in_vitro_study_count: number;
  unknown_study_population_count: number;
  sample_size_reported_count: number;
  sample_size_not_reported_count: number;
  unknown_date_count: number;
}

export interface DiseaseProfileSummary {
  concept_id: string;
  preferred_name_en: string;
  preferred_name_zh: string;
  ontology_version: string;
  document_count: number;
  analysis_count: number;
  external_article_count: number;
  saved_question_count: number;
  last_updated_at: string;
  section_counts: Partial<Record<DiseaseProfileSection, number>>;
  warnings: string[];
}

export interface DiseaseProfileDetail extends DiseaseProfileSummary {
  stats: DiseaseProfileStats;
  documents: DiseaseProfileDocument[];
  documents_next_cursor?: string | null;
  sections: Array<{
    section: DiseaseProfileSection;
    count: number;
    items: DiseaseProfileItem[];
  }>;
}

export interface DiseaseProfileList {
  items: DiseaseProfileSummary[];
  next_cursor?: string | null;
}

export interface DiseaseProfileItems {
  section: DiseaseProfileSection;
  items: DiseaseProfileItem[];
  next_cursor?: string | null;
  truncated?: boolean;
}

export interface DiseaseProfileDocumentsPage {
  items: DiseaseProfileDocument[];
  next_cursor?: string | null;
}

export type ComparisonCoverageStatus = "complete" | "partial" | "unknown";
export type ComparisonSupportStatus =
  | "supported"
  | "partially_supported"
  | "not_reported"
  | "uncertain"
  | "source_unavailable";
export type ComparisonLanguage = "en" | "zh" | "ja";

export interface ComparisonDocumentSelection {
  document_id: string;
  expected_parsed_source_hash: string;
  expected_analysis_run_id: string;
}

export interface ComparisonPreviewRequest {
  documents: ComparisonDocumentSelection[];
  language: ComparisonLanguage;
}

export interface ComparisonEvidence {
  document_id: string;
  analysis_run_id: string;
  evidence_id: string;
  quote: string;
  section_type: string;
  section_title: string;
  page_start?: number | null;
  page_end?: number | null;
  quote_truncated: boolean;
}

export interface ComparisonMethod {
  value: string;
  support_status: ComparisonSupportStatus;
  evidence: ComparisonEvidence[];
  evidence_total: number;
  evidence_truncated: boolean;
  warnings: string[];
  missing_reason?: string;
}

export interface ComparisonMethods {
  design: ComparisonMethod;
  population: ComparisonMethod;
  human_animal_in_vitro: ComparisonMethod;
  sample_size: ComparisonMethod;
  comparator: ComparisonMethod;
}

export interface ComparisonCoverage {
  status: ComparisonCoverageStatus;
  selected_chunks: number;
  total_chunks: number;
  included_sections: string[];
  omitted_sections: string[];
}

export interface ComparisonFinding {
  id: string;
  statement: string;
  explanation: string;
  evidence: ComparisonEvidence[];
  evidence_total: number;
  evidence_truncated: boolean;
  warnings: string[];
}

export interface ComparisonQuestion {
  id: string;
  question: string;
  rationale: string;
  document_id: string;
  document_ids: string[];
  analysis_run_ids: string[];
  topic: string;
  evidence: ComparisonEvidence[];
  evidence_total: number;
  evidence_truncated: boolean;
}

export interface ComparisonDocument {
  document_id: string;
  title: string;
  document_kind: string;
  document_date: string;
  open_filename: string;
  analysis_run_id: string;
  parsed_source_hash: string;
  coverage_status: ComparisonCoverageStatus;
  coverage: ComparisonCoverage;
  methods: ComparisonMethods;
  findings: ComparisonFinding[];
  findings_total: number;
  findings_truncated: boolean;
  limitations: ComparisonFinding[];
  limitations_total: number;
  limitations_truncated: boolean;
}

export interface ComparisonPreview {
  concept_id: string;
  documents: ComparisonDocument[];
  discussion_questions: ComparisonQuestion[];
  warnings: string[];
}

export interface DiseaseConceptOption {
  concept_id: string;
  preferred_name_en: string;
  preferred_name_zh: string;
  ontology_version: string;
  matched_alias: string;
}

export interface DiseaseConceptSearchResult {
  items: DiseaseConceptOption[];
}

export interface UnassignedDiseaseDocument {
  document_id: string;
  title: string;
  document_kind: string;
  language: string;
  document_date: string;
  medical_confidence: number;
  classifier_version: string;
  warnings: string[];
}

export interface UnassignedDiseaseDocumentList {
  items: UnassignedDiseaseDocument[];
  total: number;
  next_cursor?: string | null;
}

export type ClinicianQuestionStatus = "saved" | "asked" | "answered" | "dismissed";
export type ClinicianQuestionSourceStatus = "current" | "outdated" | "unavailable";

export interface ClinicianQuestion {
  id: string;
  workspace_id: string;
  document_id: string;
  document_title: string;
  analysis_run_id: string;
  suggestion_id: string;
  question: string;
  rationale: string;
  category: string;
  topic: string;
  source_kind: string;
  source_id: string;
  evidence_ids: string[];
  language: string;
  status: ClinicianQuestionStatus;
  priority: 1 | 2 | 3;
  position: number;
  user_note: string;
  version: number;
  source_status: ClinicianQuestionSourceStatus;
  evidence: VisitBriefEvidence[];
  created_at: string;
  updated_at: string;
}

export interface ClinicianQuestionList {
  items: ClinicianQuestion[];
  total: number;
}

export interface VisitBriefEvidence {
  evidence_id: string;
  chunk_id?: string | null;
  section_id?: string | null;
  section_type: string;
  section_title: string;
  page_start?: number | null;
  page_end?: number | null;
  quote: string;
  character_start?: number | null;
  character_end?: number | null;
}

export interface VisitBriefItem {
  id: string;
  clinician_question_id: string;
  document_id: string;
  document_title: string;
  document_date: string;
  parsed_source_hash: string;
  analysis_run_id: string;
  position: number;
  question: string;
  rationale: string;
  user_note: string;
  evidence: VisitBriefEvidence[];
}

export interface VisitBrief {
  id: string;
  workspace_id: string;
  status: "active" | string;
  language: string;
  generated_at: string;
  data_cutoff_at: string;
  disclaimer: string;
  items: VisitBriefItem[];
}

export interface VisitBriefList {
  items: VisitBrief[];
  total: number;
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

export type LiteratureSearchStatus = "queued" | "running" | "succeeded" | "failed" | string;

export interface LiteratureConceptSelection {
  match_id: string;
  concept_id: string;
}

export interface LiteratureSearchRequest {
  question: string;
  date_from?: string | null;
  date_to?: string | null;
  study_types: string[];
  sort: "relevance" | "newest";
  max_results: number;
  external_search_confirmed: boolean;
  query_fingerprint?: string | null;
  concept_selections: LiteratureConceptSelection[];
}

export interface DetectedLiteratureConcept {
  type: string;
  original: string;
  normalized: string;
  concept_id?: string | null;
  source?: string | null;
  source_code?: string | null;
  matched_alias?: string | null;
  match_type?: string | null;
  ontology_version?: string | null;
}

export interface LiteratureDiseaseCandidate {
  concept_id: string;
  preferred_name: string;
  display_name_zh: string;
  matched_alias: string;
  resolution: "automatic" | "confirmation_required" | "blocked" | string;
  mesh_id?: string | null;
  orpha_code?: string | null;
}

export interface AmbiguousLiteratureConcept {
  match_id: string;
  matched_text: string;
  normalized_text: string;
  status: "ready" | "needs_confirmation" | string;
  candidates: LiteratureDiseaseCandidate[];
}

export interface LiteratureSearchPreview {
  document_id: string;
  workspace_id: string;
  question: string;
  detected_concepts: DetectedLiteratureConcept[];
  resolution_status: "ready" | "needs_confirmation" | string;
  ambiguous_concepts: AmbiguousLiteratureConcept[];
  selected_concept_ids: string[];
  ontology_version?: string | null;
  redacted_fields: string[];
  pubmed_query?: string | null;
  query_fingerprint?: string | null;
  external_data: {
    provider: "pubmed" | string;
    sends_query_terms: boolean;
    sends_document_content: boolean;
    sends_uploaded_file: boolean;
    requires_confirmation: boolean;
  };
}

export interface LiteratureArticle {
  id?: string;
  source: "pubmed" | string;
  external_id: string;
  doi?: string | null;
  pmcid?: string | null;
  title: string;
  abstract?: string | null;
  journal: string;
  publication_date?: string | null;
  publication_year?: number | null;
  authors?: string[];
  publication_types: string[];
  mesh_terms?: string[];
  language?: string;
  source_url: string;
  retraction_status: string;
  metadata_hash: string;
  fetched_at?: string | null;
  provider_rank?: number;
  matched_terms?: string[];
  selected_for_analysis?: boolean;
}

export interface LiteratureSearchRun {
  run_id: string;
  user_id?: string;
  document_id: string;
  workspace_id: string;
  question: string;
  normalized_query: string;
  query_hash: string;
  provider: string;
  status: LiteratureSearchStatus;
  date_from?: string | null;
  date_to?: string | null;
  study_types?: string[];
  sort?: "relevance" | "newest" | string;
  max_results?: number;
  ontology_version?: string | null;
  detected_concepts?: DetectedLiteratureConcept[];
  selected_concept_ids?: string[];
  result_count: number;
  warnings: string[];
  error_code: string;
  error_message: string;
  attempt_count?: number;
  started_at?: string | null;
  completed_at?: string | null;
  fetched_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  articles: LiteratureArticle[];
}

export interface LiteratureMatchFeature {
  feature: string;
  score: number;
  matched_values: string[];
  explanation: string;
}

export interface LiteratureStudyCard {
  article_id: string;
  source: "pubmed" | string;
  pmid: string;
  doi?: string | null;
  pmcid?: string | null;
  title: string;
  journal: string;
  publication_year?: number | null;
  publication_types: string[];
  study_category: string;
  development_phase: string;
  abstract_available: boolean;
  relevance_score: number;
  match_specificity: "finding_specific" | "condition_only" | string;
  matched_terms: string[];
  match_reasons: string[];
  match_features: LiteratureMatchFeature[];
  abstract_quote?: string | null;
  abstract_character_start?: number | null;
  abstract_character_end?: number | null;
  retraction_status: string;
  source_url: string;
  warnings: string[];
  stale: boolean;
}

export type LiteratureFindingMatchStatus =
  | "matched"
  | "condition_only"
  | "condition_mismatch"
  | "insufficient_terms"
  | "no_candidates"
  | string;

export interface LiteratureFindingMatch {
  finding_id: string;
  finding_type: string;
  statement: string;
  plain_explanation: string;
  document_evidence_ids: string[];
  match_status: LiteratureFindingMatchStatus;
  candidates: LiteratureStudyCard[];
}

export interface LiteratureMatchSummary {
  finding_count: number;
  article_count: number;
  match_count: number;
  retracted_articles_excluded: number;
}

export interface LiteratureMatchRun {
  match_run_id: string;
  user_id?: string;
  workspace_id: string;
  document_id: string;
  analysis_run_id: string;
  search_run_id: string;
  matcher_version: string;
  input_fingerprint: string;
  status: string;
  finding_count: number;
  article_count: number;
  match_count: number;
  summary: LiteratureMatchSummary;
  excluded_articles: Record<string, number>;
  warnings: string[];
  empty_reason: string;
  stale: boolean;
  findings: LiteratureFindingMatch[];
  created_at?: string | null;
  updated_at?: string | null;
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

export const listWorkspaces = (): Promise<WorkspaceInfo[]> =>
  http.get<WorkspaceInfo[]>("/workspaces/").then((r) => r.data);

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

export const searchDiseaseConcepts = (
  query: string,
  limit = 20,
): Promise<DiseaseConceptSearchResult> =>
  http
    .get<DiseaseConceptSearchResult>("/disease-profiles/concepts/search", {
      params: { q: query, limit },
    })
    .then((r) => r.data);

export const createDiseaseLink = (
  documentId: string,
  workspaceId: string,
  body: {
    concept_id: string;
    matched_alias?: string;
    source_search_run_id?: string | null;
  },
): Promise<{ link: { id: string; document_id: string; concept_id: string }; created: boolean }> =>
  http
    .post(
      `/documents/${encodeURIComponent(documentId)}/disease-links`,
      body,
      workspaceParams(workspaceId),
    )
    .then((r) => r.data);

export const deleteDiseaseLink = (
  documentId: string,
  conceptId: string,
  workspaceId: string,
) =>
  http.delete(
    `/documents/${encodeURIComponent(documentId)}/disease-links/${encodeURIComponent(conceptId)}`,
    workspaceParams(workspaceId),
  );

export const listDiseaseProfiles = (
  workspaceId: string,
  options: { limit?: number; cursor?: string | null } = {},
): Promise<DiseaseProfileList> =>
  http
    .get<DiseaseProfileList>("/disease-profiles", {
      params: {
        workspace_id: workspaceId,
        limit: options.limit,
        cursor: options.cursor,
      },
    })
    .then((r) => r.data);

export const getDiseaseProfile = (
  conceptId: string,
  workspaceId: string,
): Promise<DiseaseProfileDetail> =>
  http
    .get<DiseaseProfileDetail>(
      `/disease-profiles/${encodeURIComponent(conceptId)}`,
      workspaceParams(workspaceId),
    )
    .then((r) => r.data);

export const previewDiseaseProfileComparison = (
  conceptId: string,
  workspaceId: string,
  body: ComparisonPreviewRequest,
): Promise<ComparisonPreview> =>
  http
    .post<ComparisonPreview>(
      `/disease-profiles/${encodeURIComponent(conceptId)}/comparison-preview`,
      body,
      workspaceParams(workspaceId),
    )
    .then((r) => r.data);

export const getDiseaseProfileDocuments = (
  conceptId: string,
  workspaceId: string,
  options: { limit?: number; cursor?: string | null } = {},
): Promise<DiseaseProfileDocumentsPage> =>
  http
    .get<DiseaseProfileDocumentsPage>(
      `/disease-profiles/${encodeURIComponent(conceptId)}/documents`,
      {
        params: {
          workspace_id: workspaceId,
          limit: options.limit,
          cursor: options.cursor,
        },
      },
    )
    .then((r) => r.data);

export const getDiseaseProfileExternalSourceDocuments = (
  conceptId: string,
  workspaceId: string,
  source: string,
  externalId: string,
  options: { limit?: number; cursor?: string | null } = {},
): Promise<DiseaseProfileDocumentsPage> =>
  http
    .get<DiseaseProfileDocumentsPage>(
      `/disease-profiles/${encodeURIComponent(conceptId)}/external-sources`,
      {
        params: {
          workspace_id: workspaceId,
          source,
          external_id: externalId,
          limit: options.limit,
          cursor: options.cursor,
        },
      },
    )
    .then((r) => r.data);

export const getDiseaseProfileItems = (
  conceptId: string,
  section: DiseaseProfileSection,
  workspaceId: string,
  options: { limit?: number; cursor?: string | null } = {},
): Promise<DiseaseProfileItems> =>
  http
    .get<DiseaseProfileItems>(
      `/disease-profiles/${encodeURIComponent(conceptId)}/items`,
      {
        params: {
          workspace_id: workspaceId,
          section,
          limit: options.limit,
          cursor: options.cursor,
        },
      },
    )
    .then((r) => r.data);

export const listUnassignedDiseaseDocuments = (
  workspaceId: string,
  options: { limit?: number; cursor?: string | null } = {},
): Promise<UnassignedDiseaseDocumentList> =>
  http
    .get<UnassignedDiseaseDocumentList>("/disease-profiles/unassigned-documents", {
      params: {
        workspace_id: workspaceId,
        limit: options.limit,
        cursor: options.cursor,
      },
    })
    .then((r) => r.data);

export const saveClinicianQuestion = (
  workspaceId: string,
  body: { analysis_run_id: string; suggestion_id: string },
): Promise<{ item: ClinicianQuestion; created: boolean; source_refreshed: boolean }> =>
  http
    .post<{ item: ClinicianQuestion; created: boolean; source_refreshed: boolean }>(
      `/workspaces/${encodeURIComponent(workspaceId)}/clinician-questions`,
      body,
    )
    .then((r) => r.data);

export const listClinicianQuestions = (
  workspaceId: string,
  options: { status?: ClinicianQuestionStatus; includeDismissed?: boolean; limit?: number } = {},
): Promise<ClinicianQuestionList> =>
  http
    .get<ClinicianQuestionList>(
      `/workspaces/${encodeURIComponent(workspaceId)}/clinician-questions`,
      {
        params: {
          status: options.status,
          include_dismissed: options.includeDismissed,
          limit: options.limit,
        },
      },
    )
    .then((r) => r.data);

export const updateClinicianQuestion = (
  workspaceId: string,
  questionId: string,
  body: {
    status?: ClinicianQuestionStatus;
    priority?: 1 | 2 | 3;
    user_note?: string;
    expected_version: number;
  },
): Promise<ClinicianQuestion> =>
  http
    .patch<ClinicianQuestion>(
      `/workspaces/${encodeURIComponent(workspaceId)}/clinician-questions/${encodeURIComponent(questionId)}`,
      body,
    )
    .then((r) => r.data);

export const reorderClinicianQuestions = (
  workspaceId: string,
  body: {
    question_id: string;
    target_question_id: string;
    expected_version: number;
    target_expected_version: number;
  },
): Promise<ClinicianQuestion[]> =>
  http
    .patch<ClinicianQuestion[]>(
      `/workspaces/${encodeURIComponent(workspaceId)}/clinician-questions/reorder`,
      body,
    )
    .then((r) => r.data);

export const deleteClinicianQuestion = (workspaceId: string, questionId: string) =>
  http.delete(
    `/workspaces/${encodeURIComponent(workspaceId)}/clinician-questions/${encodeURIComponent(questionId)}`,
  );

export const createVisitBrief = (
  workspaceId: string,
  body: { question_ids: string[]; include_user_notes: boolean },
): Promise<VisitBrief> =>
  http
    .post<VisitBrief>(`/workspaces/${encodeURIComponent(workspaceId)}/visit-briefs`, body)
    .then((r) => r.data);

export const listVisitBriefs = (workspaceId: string, limit = 20): Promise<VisitBriefList> =>
  http
    .get<VisitBriefList>(`/workspaces/${encodeURIComponent(workspaceId)}/visit-briefs`, {
      params: { limit },
    })
    .then((r) => r.data);

export const getVisitBrief = (workspaceId: string, briefId: string): Promise<VisitBrief> =>
  http
    .get<VisitBrief>(
      `/workspaces/${encodeURIComponent(workspaceId)}/visit-briefs/${encodeURIComponent(briefId)}`,
    )
    .then((r) => r.data);

export const deleteVisitBrief = (workspaceId: string, briefId: string) =>
  http.delete(
    `/workspaces/${encodeURIComponent(workspaceId)}/visit-briefs/${encodeURIComponent(briefId)}`,
  );

export const previewLiteratureSearch = (
  documentId: string,
  body: LiteratureSearchRequest,
  workspaceId?: string | null,
): Promise<LiteratureSearchPreview> =>
  http
    .post<LiteratureSearchPreview>(
      `/documents/${encodeURIComponent(documentId)}/literature-search/preview`,
      body,
      workspaceParams(workspaceId),
    )
    .then((r) => r.data);

export const startLiteratureSearch = (
  documentId: string,
  body: LiteratureSearchRequest,
  workspaceId?: string | null,
): Promise<LiteratureSearchRun> =>
  http
    .post<LiteratureSearchRun & { created?: boolean }>(
      `/documents/${encodeURIComponent(documentId)}/literature-search`,
      body,
      workspaceParams(workspaceId),
    )
    .then((r) => r.data);

export const getLiteratureSearchRun = (
  runId: string,
  workspaceId?: string | null,
): Promise<LiteratureSearchRun> =>
  http
    .get<LiteratureSearchRun>(
      `/literature-search-runs/${encodeURIComponent(runId)}`,
      workspaceParams(workspaceId),
    )
    .then((r) => r.data);

export const getLatestLiteratureSearch = (
  documentId: string,
  workspaceId?: string | null,
): Promise<LiteratureSearchRun> =>
  http
    .get<LiteratureSearchRun>(
      `/documents/${encodeURIComponent(documentId)}/literature-searches/latest`,
      workspaceParams(workspaceId),
    )
    .then((r) => r.data);

export const createLiteratureMatch = (
  documentId: string,
  body: { analysis_run_id: string; search_run_id: string },
  workspaceId?: string | null,
): Promise<LiteratureMatchRun> =>
  http
    .post<LiteratureMatchRun & { created?: boolean }>(
      `/documents/${encodeURIComponent(documentId)}/literature-matches`,
      body,
      workspaceParams(workspaceId),
    )
    .then((r) => r.data);

export const getLiteratureMatchRun = (
  matchRunId: string,
  workspaceId?: string | null,
): Promise<LiteratureMatchRun> =>
  http
    .get<LiteratureMatchRun>(
      `/literature-match-runs/${encodeURIComponent(matchRunId)}`,
      workspaceParams(workspaceId),
    )
    .then((r) => r.data);

export const getLatestLiteratureMatch = (
  documentId: string,
  workspaceId?: string | null,
): Promise<LiteratureMatchRun> =>
  http
    .get<LiteratureMatchRun>(
      `/documents/${encodeURIComponent(documentId)}/literature-matches/latest`,
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
