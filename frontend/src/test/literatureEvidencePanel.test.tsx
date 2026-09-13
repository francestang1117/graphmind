import { StrictMode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import LiteratureEvidencePanel from "../components/upload/literature/LiteratureEvidencePanel";

const api = vi.hoisted(() => ({
  previewLiteratureSearch: vi.fn(),
  startLiteratureSearch: vi.fn(),
  getLiteratureSearchRun: vi.fn(),
  getLatestLiteratureSearch: vi.fn(),
  createLiteratureMatch: vi.fn(),
  getLiteratureMatchRun: vi.fn(),
  getLatestLiteratureMatch: vi.fn(),
}));

vi.mock("../services/api", () => api);

const preview = {
  document_id: "doc-1",
  workspace_id: "workspace-1",
  question: "Does migalastat help with Fabry disease?",
  detected_concepts: [
    {
      type: "drug",
      original: "米加司他",
      normalized: "migalastat",
      concept_id: "drug:migalastat",
      source: "local_ontology",
    },
  ],
  resolution_status: "ready",
  ambiguous_concepts: [],
  selected_concept_ids: [],
  ontology_version: "medical-seed-test",
  redacted_fields: [],
  pubmed_query: '("Fabry disease"[Title/Abstract]) AND migalastat[Title/Abstract]',
  query_fingerprint: "a".repeat(64),
  external_data: {
    provider: "pubmed",
    sends_query_terms: true,
    sends_document_content: false,
    sends_uploaded_file: false,
    requires_confirmation: true,
  },
};

const searchRun = {
  run_id: "search-1",
  document_id: "doc-1",
  workspace_id: "workspace-1",
  question: preview.question,
  normalized_query: preview.pubmed_query,
  query_hash: preview.query_fingerprint,
  provider: "pubmed",
  status: "succeeded",
  result_count: 1,
  warnings: [],
  error_code: "",
  error_message: "",
  articles: [],
};

const matchRun = {
  match_run_id: "match-1",
  workspace_id: "workspace-1",
  document_id: "doc-1",
  analysis_run_id: "analysis-1",
  search_run_id: "search-1",
  matcher_version: "matcher-v1",
  input_fingerprint: "b".repeat(64),
  status: "succeeded",
  finding_count: 1,
  article_count: 1,
  match_count: 1,
  summary: {
    finding_count: 1,
    article_count: 1,
    match_count: 1,
    retracted_articles_excluded: 0,
  },
  excluded_articles: {},
  warnings: [],
  empty_reason: "",
  stale: false,
  findings: [
    {
      finding_id: "finding-1",
      finding_type: "key_finding",
      statement: "Migalastat was associated with a change in proteinuria.",
      plain_explanation: "This is a retrieval match for the finding, not proof of benefit.",
      document_evidence_ids: ["evidence-1"],
      match_status: "matched",
      candidates: [
        {
          article_id: "article-1",
          source: "pubmed",
          pmid: "12345678",
          doi: "10.1000/example",
          title: "Migalastat and proteinuria in Fabry disease",
          journal: "Example Medicine",
          publication_year: 2025,
          publication_types: ["Clinical Trial"],
          study_category: "clinical_trial",
          development_phase: "not_applicable",
          abstract_available: true,
          relevance_score: 82,
          match_specificity: "finding_specific",
          matched_terms: ["migalastat", "proteinuria"],
          match_reasons: ["Finding-specific terms overlap with the abstract."],
          match_features: [],
          abstract_quote: "The study evaluated changes in proteinuria.",
          retraction_status: "normal",
          source_url: "https://pubmed.ncbi.nlm.nih.gov/12345678/",
          warnings: [],
          stale: false,
        },
      ],
    },
  ],
};

function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <StrictMode>
        <LiteratureEvidencePanel
          documentId="doc-1"
          workspaceId="workspace-1"
          analysisRunId="analysis-1"
        />
      </StrictMode>
    </QueryClientProvider>,
  );
}

describe("LiteratureEvidencePanel", () => {
  afterEach(() => cleanup());

  beforeEach(() => {
    vi.clearAllMocks();
    api.getLatestLiteratureSearch.mockRejectedValue({ response: { status: 404 } });
    api.getLatestLiteratureMatch.mockRejectedValue({ response: { status: 404 } });
  });

  it("previews, confirms, searches, and matches exactly once", async () => {
    const user = userEvent.setup();
    api.previewLiteratureSearch.mockResolvedValue(preview);
    api.startLiteratureSearch.mockResolvedValue({ ...searchRun, status: "queued" });
    api.getLiteratureSearchRun.mockResolvedValue(searchRun);
    api.createLiteratureMatch.mockResolvedValue(matchRun);

    renderPanel();
    await user.type(screen.getByLabelText("Research question"), preview.question);
    await user.click(screen.getByRole("button", { name: "Preview PubMed query" }));

    expect(await screen.findByText("Review the PubMed query")).toBeInTheDocument();
    expect(screen.getByText(preview.pubmed_query)).toBeInTheDocument();
    expect(api.startLiteratureSearch).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Confirm and search" }));

    await waitFor(() => expect(api.createLiteratureMatch).toHaveBeenCalledTimes(1));
    expect(api.startLiteratureSearch).toHaveBeenCalledWith(
      "doc-1",
      expect.objectContaining({
        external_search_confirmed: true,
        query_fingerprint: preview.query_fingerprint,
      }),
      "workspace-1",
    );
    expect(await screen.findByText("Migalastat and proteinuria in Fabry disease")).toBeInTheDocument();
    expect(screen.getByText("Finding-specific candidate")).toBeInTheDocument();
  });

  it("requires an ambiguous concept to be selected and re-previewed", async () => {
    const user = userEvent.setup();
    const ambiguousPreview = {
      ...preview,
      resolution_status: "needs_confirmation",
      pubmed_query: null,
      query_fingerprint: null,
      ambiguous_concepts: [
        {
          match_id: "match-ambiguous",
          matched_text: "ALS",
          normalized_text: "als",
          status: "needs_confirmation",
          candidates: [
            {
              concept_id: "mesh:D000690",
              preferred_name: "Amyotrophic Lateral Sclerosis",
              display_name_zh: "肌萎缩侧索硬化",
              matched_alias: "ALS",
              resolution: "confirmation_required",
              mesh_id: "D000690",
            },
          ],
        },
      ],
    };
    api.previewLiteratureSearch
      .mockResolvedValueOnce(ambiguousPreview)
      .mockResolvedValueOnce(preview);

    renderPanel();
    await user.type(screen.getByLabelText("Research question"), "What is known about ALS?");
    await user.click(screen.getByRole("button", { name: "Preview PubMed query" }));
    expect(await screen.findByText("Choose the disease concept")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm and search" })).toBeDisabled();

    await user.click(screen.getByRole("radio", { name: /肌萎缩侧索硬化/ }));
    await user.click(screen.getByRole("button", { name: "Rebuild preview" }));

    await waitFor(() => expect(api.previewLiteratureSearch).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("Ready to search")).toBeInTheDocument();
  });

  it("hides a match saved for an older analysis run", async () => {
    api.getLatestLiteratureMatch.mockResolvedValue({
      ...matchRun,
      analysis_run_id: "analysis-old",
    });

    renderPanel();

    expect(await screen.findByText(/older medical analysis/)).toBeInTheDocument();
    expect(screen.queryByText("Migalastat and proteinuria in Fabry disease")).not.toBeInTheDocument();
  });

  it("does not reuse a current-analysis match for a newer search run", async () => {
    api.getLatestLiteratureSearch.mockResolvedValue({ ...searchRun, run_id: "search-2" });
    api.getLatestLiteratureMatch.mockResolvedValue(matchRun);
    api.createLiteratureMatch.mockResolvedValue({ ...matchRun, search_run_id: "search-2" });

    renderPanel();

    await waitFor(() => expect(api.createLiteratureMatch).toHaveBeenCalledWith(
      "doc-1",
      { analysis_run_id: "analysis-1", search_run_id: "search-2" },
      "workspace-1",
    ));
  });

  it("does not render an untrusted source URL as a link", async () => {
    api.getLatestLiteratureMatch.mockResolvedValue({
      ...matchRun,
      findings: [{
        ...matchRun.findings[0],
        candidates: [{
          ...matchRun.findings[0].candidates[0],
          source_url: "javascript:alert(1)",
        }],
      }],
    });

    renderPanel();

    expect(await screen.findByText("Migalastat and proteinuria in Fabry disease")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "View on PubMed" })).not.toBeInTheDocument();
  });
});
