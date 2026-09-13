import { useEffect, useRef, useState } from "react";
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  createLiteratureMatch,
  getLatestLiteratureMatch,
  getLatestLiteratureSearch,
  getLiteratureSearchRun,
  previewLiteratureSearch,
  startLiteratureSearch,
  type LiteratureConceptSelection,
  type LiteratureMatchRun,
  type LiteratureSearchPreview,
  type LiteratureSearchRequest,
  type LiteratureSearchRun,
} from "../services/api";

export const LITERATURE_STUDY_TYPES = [
  { value: "systematic review", label: "Systematic review" },
  { value: "meta-analysis", label: "Meta-analysis" },
  { value: "randomized controlled trial", label: "Randomized controlled trial" },
  { value: "clinical trial", label: "Clinical trial" },
  { value: "observational study", label: "Observational study" },
  { value: "case report", label: "Case report" },
  { value: "guideline", label: "Guideline" },
] as const;

export interface LiteratureFormState {
  question: string;
  dateFrom: string;
  dateTo: string;
  studyTypes: string[];
  sort: "relevance" | "newest";
  maxResults: number;
}

const INITIAL_FORM: LiteratureFormState = {
  question: "",
  dateFrom: "",
  dateTo: "",
  studyTypes: [],
  sort: "relevance",
  maxResults: 20,
};

const ACTIVE_STATUSES = new Set(["queued", "running"]);

function errorDetails(error: unknown) {
  const requestError = (error && typeof error === "object" ? error : {}) as {
    response?: {
      status?: number;
      data?: {
        code?: string;
        message?: string;
        detail?: { code?: string; message?: string; details?: unknown } | string;
        details?: unknown;
      };
    };
    message?: string;
  };
  const data = requestError.response?.data;
  const detail = typeof data?.detail === "object" ? data.detail : undefined;
  const code = data?.code ?? detail?.code;
  const message = data?.message
    ?? detail?.message
    ?? (typeof data?.detail === "string" ? data.detail : undefined)
    ?? requestError.message;
  return {
    code,
    message,
    status: requestError.response?.status,
    details: data?.details ?? detail?.details,
  };
}

function isLiteraturePreview(value: unknown): value is LiteratureSearchPreview {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<LiteratureSearchPreview>;
  return typeof candidate.document_id === "string"
    && typeof candidate.workspace_id === "string"
    && Array.isArray(candidate.detected_concepts)
    && Array.isArray(candidate.ambiguous_concepts)
    && typeof candidate.external_data === "object";
}

function readableError(error: unknown, fallback: string) {
  const { code, message } = errorDetails(error);
  const knownMessages: Record<string, string> = {
    literature_search_disabled: "Literature search is disabled on the server.",
    literature_rate_limiter_unavailable: "PubMed is temporarily unavailable. Please try again later.",
    literature_provider_unavailable: "PubMed could not be reached. Please try again later.",
    literature_concept_confirmation_required: "Choose a disease concept before searching PubMed.",
    external_search_confirmation_required: "Confirm the displayed PubMed query before searching.",
    external_search_query_changed: "The query changed. Generate a new preview and confirm it again.",
    literature_queue_failed: "The search could not be queued. Please try again.",
    literature_matching_disabled: "Evidence matching is disabled on the server.",
    literature_match_no_findings: "This analysis does not contain matchable findings yet.",
    literature_match_storage_unavailable: "Evidence matching storage is temporarily unavailable.",
  };
  return (code && knownMessages[code]) || message || fallback;
}

async function nullable<T>(loader: () => Promise<T>) {
  try {
    return await loader();
  } catch (error) {
    if (errorDetails(error).status === 404) return null;
    throw error;
  }
}

function requestFromForm(
  form: LiteratureFormState,
  conceptSelections: LiteratureConceptSelection[],
  preview?: LiteratureSearchPreview | null,
): LiteratureSearchRequest {
  return {
    question: form.question.trim(),
    date_from: form.dateFrom || null,
    date_to: form.dateTo || null,
    study_types: form.studyTypes,
    sort: form.sort,
    max_results: form.maxResults,
    external_search_confirmed: Boolean(preview?.query_fingerprint),
    query_fingerprint: preview?.query_fingerprint ?? null,
    concept_selections: conceptSelections,
  };
}

function pollInterval(query: { state: { data?: LiteratureSearchRun | null } }) {
  const status = query.state.data?.status;
  if (!status || !ACTIVE_STATUSES.has(status)) return false;
  const startedAt = Number(query.state.data?.started_at ? Date.parse(query.state.data.started_at) : NaN);
  const createdAt = Number(query.state.data?.created_at ? Date.parse(query.state.data.created_at) : NaN);
  const elapsed = Date.now() - (Number.isFinite(startedAt) ? startedAt : Number.isFinite(createdAt) ? createdAt : Date.now());
  if (elapsed < 5_000) return 1_000;
  if (elapsed < 20_000) return 2_000;
  return 5_000;
}

export function useLiteratureEvidence(
  documentId: string,
  workspaceId: string | null | undefined,
  analysisRunId: string,
) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<LiteratureFormState>(INITIAL_FORM);
  const [preview, setPreview] = useState<LiteratureSearchPreview | null>(null);
  const [conceptSelections, setConceptSelections] = useState<LiteratureConceptSelection[]>([]);
  const [activeSearchRunId, setActiveSearchRunId] = useState<string | null>(null);
  const [activeMatchRun, setActiveMatchRun] = useState<LiteratureMatchRun | null>(null);
  const [matchingSearchRunId, setMatchingSearchRunId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const hydratedForm = useRef(false);
  const matchAttemptKey = useRef<string | null>(null);

  const scopeKey = workspaceId || "default";
  const latestSearchKey = ["literature-search-latest", scopeKey, documentId];
  const latestMatchKey = ["literature-match-latest", scopeKey, documentId];

  const latestSearchQuery = useQuery({
    queryKey: latestSearchKey,
    queryFn: () => nullable(() => getLatestLiteratureSearch(documentId, workspaceId)),
    enabled: Boolean(documentId),
    refetchOnWindowFocus: false,
    retry: (failureCount, requestError) => errorDetails(requestError).status !== 404 && failureCount < 1,
  });

  const latestSearch = latestSearchQuery.data ?? null;
  const effectiveSearchRunId = activeSearchRunId ?? latestSearch?.run_id ?? null;

  const activeSearchQuery = useQuery({
    queryKey: ["literature-search-run", scopeKey, effectiveSearchRunId],
    queryFn: () => getLiteratureSearchRun(effectiveSearchRunId as string, workspaceId),
    enabled: Boolean(effectiveSearchRunId),
    refetchOnWindowFocus: false,
    refetchInterval: pollInterval,
  });

  const latestMatchQuery = useQuery({
    queryKey: latestMatchKey,
    queryFn: () => nullable(() => getLatestLiteratureMatch(documentId, workspaceId)),
    enabled: Boolean(documentId),
    refetchOnWindowFocus: false,
    retry: (failureCount, requestError) => errorDetails(requestError).status !== 404 && failureCount < 1,
  });

  const previewMutation = useMutation({
    mutationFn: (body: LiteratureSearchRequest) => previewLiteratureSearch(documentId, body, workspaceId),
    onSuccess: (nextPreview) => {
      setPreview(nextPreview);
      setError("");
    },
    onError: (requestError) => {
      setPreview(null);
      setError(readableError(requestError, "Could not preview the PubMed query."));
    },
  });

  const startMutation = useMutation({
    mutationFn: (body: LiteratureSearchRequest) => startLiteratureSearch(documentId, body, workspaceId),
    onSuccess: (nextRun) => {
      setActiveSearchRunId(nextRun.run_id);
      setError("");
      queryClient.setQueryData(["literature-search-run", scopeKey, nextRun.run_id], nextRun);
      void queryClient.invalidateQueries({ queryKey: latestSearchKey });
    },
    onError: (requestError) => {
      const details = errorDetails(requestError).details;
      if (isLiteraturePreview(details)) setPreview(details);
      setError(readableError(requestError, "Could not start the PubMed search."));
    },
  });

  const matchMutation = useMutation({
    mutationFn: (searchRunId: string) => createLiteratureMatch(
      documentId,
      { analysis_run_id: analysisRunId, search_run_id: searchRunId },
      workspaceId,
    ),
    onMutate: (searchRunId) => {
      setMatchingSearchRunId(searchRunId);
      setError("");
    },
    onSuccess: (nextMatch) => {
      setActiveMatchRun(nextMatch);
      setMatchingSearchRunId(null);
      void queryClient.invalidateQueries({ queryKey: latestMatchKey });
    },
    onError: (requestError) => {
      setMatchingSearchRunId(null);
      matchAttemptKey.current = null;
      setError(readableError(requestError, "Could not match the analysis to PubMed results."));
    },
  });

  const searchRun = activeSearchQuery.data ?? latestSearch;
  const latestMatch = activeMatchRun ?? latestMatchQuery.data ?? null;
  const currentMatch = latestMatch?.analysis_run_id === analysisRunId ? latestMatch : null;
  const matchForCurrentSearch = currentMatch
    && (!effectiveSearchRunId || currentMatch.search_run_id === effectiveSearchRunId)
    ? currentMatch
    : null;
  const outdatedMatch = latestMatch && latestMatch.analysis_run_id !== analysisRunId ? latestMatch : null;

  useEffect(() => {
    if (!latestSearch) return;
    if (hydratedForm.current) return;
    setForm({
      question: latestSearch.question,
      dateFrom: latestSearch.date_from ?? "",
      dateTo: latestSearch.date_to ?? "",
      studyTypes: latestSearch.study_types ?? [],
      sort: latestSearch.sort === "newest" ? "newest" : "relevance",
      maxResults: latestSearch.max_results ?? 20,
    });
    hydratedForm.current = true;
  }, [latestSearch]);

  useEffect(() => {
    if (searchRun?.status !== "succeeded" || !searchRun.run_id) return;
    if (matchForCurrentSearch || matchMutation.isPending) return;
    const attemptKey = `${analysisRunId}:${searchRun.run_id}`;
    if (matchAttemptKey.current === attemptKey) return;
    matchAttemptKey.current = attemptKey;
    matchMutation.mutate(searchRun.run_id);
  }, [analysisRunId, matchForCurrentSearch, matchMutation, searchRun]);

  const updateForm = (field: keyof LiteratureFormState, value: string | number) => {
    setForm((previous) => ({ ...previous, [field]: value } as LiteratureFormState));
    setPreview(null);
    setConceptSelections([]);
    setError("");
  };

  const toggleStudyType = (studyType: string) => {
    setForm((previous) => ({
      ...previous,
      studyTypes: previous.studyTypes.includes(studyType)
        ? previous.studyTypes.filter((item) => item !== studyType)
        : [...previous.studyTypes, studyType],
    }));
    setPreview(null);
    setConceptSelections([]);
    setError("");
  };

  const previewSearch = () => {
    if (!form.question.trim()) {
      setError("Enter a research question before generating a PubMed preview.");
      return;
    }
    setError("");
    previewMutation.mutate(requestFromForm(form, conceptSelections));
  };

  const startSearch = () => {
    if (!preview || preview.resolution_status !== "ready" || !preview.query_fingerprint) {
      setError("Generate a ready query preview before starting the search.");
      return;
    }
    setError("");
    startMutation.mutate(requestFromForm(form, conceptSelections, preview));
  };

  const selectConcept = (matchId: string, conceptId: string) => {
    setConceptSelections((previous) => [
      ...previous.filter((selection) => selection.match_id !== matchId),
      { match_id: matchId, concept_id: conceptId },
    ]);
    setError("");
  };

  const matchSearch = (searchRunId: string, force = false) => {
    if (!force && matchAttemptKey.current === `${analysisRunId}:${searchRunId}`) return;
    matchAttemptKey.current = `${analysisRunId}:${searchRunId}`;
    matchMutation.mutate(searchRunId);
  };

  const retrySearch = () => {
    setActiveSearchRunId(null);
    setPreview(null);
    setError("");
  };

  return {
    form,
    updateForm,
    toggleStudyType,
    preview,
    conceptSelections,
    selectConcept,
    previewSearch,
    previewLoading: previewMutation.isPending,
    startSearch,
    startLoading: startMutation.isPending,
    searchRun,
    searchLoading: latestSearchQuery.isLoading || activeSearchQuery.isFetching,
    searchError: latestSearchQuery.error ? readableError(latestSearchQuery.error, "Could not load the latest PubMed search.") : "",
    retrySearch,
    matchSearch,
    matchLoading: matchMutation.isPending,
    matchingSearchRunId,
    matchRun: matchForCurrentSearch,
    outdatedMatch,
    error,
    clearError: () => setError(""),
  };
}
