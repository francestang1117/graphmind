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
  { value: "systematic_review", label: "Systematic review" },
  { value: "meta_analysis", label: "Meta-analysis" },
  { value: "randomized_controlled_trial", label: "Randomized controlled trial" },
  { value: "clinical_trial", label: "Clinical trial" },
  { value: "observational_study", label: "Observational study" },
  { value: "case_report", label: "Case report" },
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

const STUDY_TYPE_ALIASES: Record<string, string> = {
  "systematic review": "systematic_review",
  "meta-analysis": "meta_analysis",
  "meta analysis": "meta_analysis",
  "randomized controlled trial": "randomized_controlled_trial",
  "clinical trial": "clinical_trial",
  "observational study": "observational_study",
  "case report": "case_report",
};

function normalizeStudyTypes(values: string[]) {
  return [...new Set(values
    .map((value) => value.trim().toLowerCase())
    .filter(Boolean)
    .map((value) => STUDY_TYPE_ALIASES[value] ?? value))];
}

function sameStudyTypes(left: string[], right: string[]) {
  const normalizedLeft = normalizeStudyTypes(left).sort();
  const normalizedRight = normalizeStudyTypes(right).sort();
  return normalizedLeft.length === normalizedRight.length
    && normalizedLeft.every((value, index) => value === normalizedRight[index]);
}

function formMatchesSearchRun(form: LiteratureFormState, run: LiteratureSearchRun) {
  return form.question.trim() === run.question.trim()
    && form.dateFrom === (run.date_from ?? "")
    && form.dateTo === (run.date_to ?? "")
    && form.sort === (run.sort === "newest" ? "newest" : "relevance")
    && form.maxResults === (run.max_results ?? 20)
    && sameStudyTypes(form.studyTypes, run.study_types ?? []);
}

function formFromSearchRun(run: LiteratureSearchRun): LiteratureFormState {
  return {
    question: run.question,
    dateFrom: run.date_from ?? "",
    dateTo: run.date_to ?? "",
    studyTypes: normalizeStudyTypes(run.study_types ?? []),
    sort: run.sort === "newest" ? "newest" : "relevance",
    maxResults: run.max_results ?? 20,
  };
}

function messageFromDetail(value: unknown): string | undefined {
  if (typeof value === "string") return value;
  if (Array.isArray(value)) {
    const messages = value
      .map((item) => messageFromDetail(item))
      .filter((message): message is string => Boolean(message));
    return messages.length > 0 ? messages.join("; ") : undefined;
  }
  if (!value || typeof value !== "object") return undefined;
  const record = value as { message?: unknown; msg?: unknown };
  if (typeof record.message === "string") return record.message;
  if (typeof record.msg === "string") return record.msg;
  return undefined;
}

function errorDetails(error: unknown) {
  const requestError = (error && typeof error === "object" ? error : {}) as {
    response?: {
      status?: number;
      data?: {
        code?: string;
        message?: string;
        detail?: unknown;
        details?: unknown;
      };
    };
    message?: string;
  };
  const data = requestError.response?.data;
  const detail = data?.detail && typeof data.detail === "object" && !Array.isArray(data.detail)
    ? data.detail as { code?: string; message?: string; details?: unknown }
    : undefined;
  const code = data?.code ?? detail?.code;
  const message = data?.message
    ?? detail?.message
    ?? messageFromDetail(data?.detail)
    ?? messageFromDetail(data?.details)
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
    && typeof candidate.external_data === "object"
    && candidate.external_data !== null;
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
    study_types: normalizeStudyTypes(form.studyTypes),
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
  const [formHydrated, setFormHydrated] = useState(false);
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
  const draftIsDirty = Boolean(
    searchRun
      && formHydrated
      && !formMatchesSearchRun(form, searchRun),
  );

  useEffect(() => {
    if (!latestSearch) return;
    if (hydratedForm.current) return;
    setForm(formFromSearchRun(latestSearch));
    hydratedForm.current = true;
    setFormHydrated(true);
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
    if (form.dateFrom && form.dateTo && form.dateFrom > form.dateTo) {
      setError("The From date must be on or before the To date.");
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

  const retrySearchStatus = () => {
    setError("");
    void (effectiveSearchRunId ? activeSearchQuery.refetch() : latestSearchQuery.refetch());
  };

  const restoreSavedSearch = () => {
    if (!searchRun) return;
    setForm(formFromSearchRun(searchRun));
    hydratedForm.current = true;
    setFormHydrated(true);
    setPreview(null);
    setConceptSelections([]);
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
    searchError: activeSearchQuery.error
      ? readableError(activeSearchQuery.error, "Unable to refresh the PubMed search status.")
      : latestSearchQuery.error
        ? readableError(latestSearchQuery.error, "Could not load the latest PubMed search.")
        : "",
    retrySearch,
    retrySearchStatus,
    draftIsDirty,
    restoreSavedSearch,
    matchSearch,
    matchLoading: matchMutation.isPending,
    matchingSearchRunId,
    matchRun: matchForCurrentSearch,
    outdatedMatch,
    error,
    clearError: () => setError(""),
  };
}
