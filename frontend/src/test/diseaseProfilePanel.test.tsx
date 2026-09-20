import axios from "axios";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import DiseaseProfilePanel from "../components/DiseaseProfilePanel";
import type { ComparisonPreview, UnassignedDiseaseDocument } from "../services/api";

const hooks = vi.hoisted(() => ({
  useDiseaseComparisonPreview: vi.fn(),
  useDiseaseProfiles: vi.fn(),
  useDiseaseProfileExternalSourceDocuments: vi.fn(),
  useDiseaseProfileItems: vi.fn(),
  useDiseaseConceptSearch: vi.fn(),
}));

vi.mock("../hooks/useDiseaseProfiles", () => hooks);

const finding = {
  id: "run-1:key_findings:finding-1",
  item_type: "finding",
  section: "key_findings",
  document_id: "document-1",
  document_ids: ["document-1"],
  document_title: "fabry-study.pdf",
  document_titles: ["fabry-study.pdf"],
  document_kind: "research_paper",
  document_date: "2026-01-01",
  analysis_run_id: "run-1",
  parsed_source_hash: "parsed-1",
  source_status: "current",
  title: "direct_statement",
  text: "The study reported a measured outcome.",
  explanation: "This is the source finding.",
  value: "",
  support_status: "supported",
  term: "",
  question: "",
  rationale: "",
  category: "",
  topic: "",
  source_kind: "",
  source_id: "",
  evidence_ids: ["EVIDENCE-1"],
  evidence: [{
    source_type: "document_evidence",
    evidence_id: "EVIDENCE-1",
    document_id: "document-1",
    document_title: "fabry-study.pdf",
    document_date: "2026-01-01",
    analysis_run_id: "run-1",
    parsed_source_hash: "parsed-1",
    section_type: "results",
    section_title: "Results",
    page_start: 4,
    page_end: 4,
    quote: "The measured outcome changed after the intervention.",
    source: "",
    external_id: "",
    source_url: "",
    retraction_status: "unknown",
    flagged: false,
    warnings: [],
  }],
  source: "",
  external_id: "",
  doi: null,
  pmcid: null,
  journal: "",
  publication_date: null,
  publication_year: null,
  publication_types: [],
  source_url: "",
  retraction_status: "unknown",
  flagged: false,
  warnings: [],
  relevance_score: null,
  match_specificity: "",
};

const summary = {
  concept_id: "mesh:D000795",
  preferred_name_en: "Fabry Disease",
  preferred_name_zh: "法布雷病",
  ontology_version: "test-v1",
  document_count: 1,
  analysis_count: 1,
  external_article_count: 0,
  saved_question_count: 0,
  last_updated_at: "2026-09-18T00:00:00+00:00",
  section_counts: { key_findings: 1 },
  warnings: [],
};

const detail = {
  ...summary,
  stats: {
    document_count: 1,
    research_paper_count: 1,
    guideline_count: 0,
    other_medical_document_count: 0,
    valid_analysis_count: 1,
    expired_analysis_count: 0,
    external_article_count: 0,
    flagged_article_count: 0,
    comparator_reported_count: 0,
    comparator_not_reported_count: 1,
    human_study_count: 1,
    animal_study_count: 0,
    in_vitro_study_count: 0,
    unknown_study_population_count: 0,
    sample_size_reported_count: 1,
    sample_size_not_reported_count: 0,
    unknown_date_count: 0,
  },
  documents: [{
    document_id: "document-1",
    title: "fabry-study.pdf",
    document_kind: "research_paper",
    language: "en",
    document_date: "2026-01-01",
    parsed_source_hash: "parsed-1",
    current_analysis_run_id: "run-1",
    source_status: "current",
    warnings: [],
  }],
  sections: [{ section: "key_findings", count: 1, items: [finding] }],
};

function configure({
  profiles = [summary],
  selectedConceptId = "mesh:D000795",
  unassigned = [],
  unassignedTotal = unassigned.length,
  hasMoreProfiles = false,
  hasMoreUnassigned = false,
  loadingMoreUnassigned = false,
  loadMoreUnassigned = vi.fn().mockResolvedValue(undefined),
  linkedDocuments,
  hasMoreDocuments = false,
  loadingMoreDocuments = false,
  loadMoreDocuments = vi.fn().mockResolvedValue(undefined),
  documentsQuery,
  detailValue = detail,
  comparisonMutation,
}: {
  profiles?: typeof summary[];
  selectedConceptId?: string | null;
  unassigned?: UnassignedDiseaseDocument[];
  unassignedTotal?: number;
  hasMoreProfiles?: boolean;
  hasMoreUnassigned?: boolean;
  loadingMoreUnassigned?: boolean;
  loadMoreUnassigned?: () => Promise<unknown>;
  linkedDocuments?: typeof detail.documents;
  hasMoreDocuments?: boolean;
  loadingMoreDocuments?: boolean;
  loadMoreDocuments?: () => Promise<unknown>;
  documentsQuery?: { error: unknown; refetch: () => Promise<unknown> };
  detailValue?: typeof detail;
  comparisonMutation?: {
    data?: unknown;
    error?: unknown;
    isPending?: boolean;
    mutateAsync?: ReturnType<typeof vi.fn>;
    reset?: ReturnType<typeof vi.fn>;
  };
} = {}) {
  const linkDocument = vi.fn().mockResolvedValue(undefined);
  const unlinkDocument = vi.fn().mockResolvedValue(undefined);
  const loadMoreProfiles = vi.fn().mockResolvedValue(undefined);
  const refreshCurrentProfile = vi.fn().mockResolvedValue(undefined);
  const profilesState = {
    list: profiles,
    hasMoreProfiles,
    loadingMoreProfiles: false,
    loadMoreProfiles,
    selectedConceptId,
    listQuery: { isLoading: false, error: null, refetch: vi.fn() },
    detail: detailValue,
    detailQuery: { isLoading: false, error: null, refetch: vi.fn() },
    unassigned,
    unassignedTotal,
    hasMoreUnassigned,
    loadingMoreUnassigned,
    loadMoreUnassigned,
    unassignedQuery: { isLoading: false, error: null, refetch: vi.fn() },
    linkedDocuments,
    hasMoreDocuments,
    loadingMoreDocuments,
    loadMoreDocuments,
    documentsQuery: documentsQuery ?? { error: null, refetch: vi.fn() },
    linkDocument,
    linking: false,
    unlinkDocument,
    unlinking: false,
    refreshCurrentProfile,
  };
  hooks.useDiseaseProfiles.mockReturnValue(profilesState);
  hooks.useDiseaseProfileItems.mockReturnValue({ data: undefined, isLoading: false });
  hooks.useDiseaseProfileExternalSourceDocuments.mockReturnValue({
    data: { pages: [] },
    isLoading: false,
    isFetchingNextPage: false,
    hasNextPage: false,
    error: null,
    fetchNextPage: vi.fn(),
    refetch: vi.fn(),
  });
  hooks.useDiseaseConceptSearch.mockReturnValue({
    data: {
      items: [{
        concept_id: "mesh:D000795",
        preferred_name_en: "Fabry Disease",
        preferred_name_zh: "法布雷病",
        ontology_version: "test-v1",
        matched_alias: "法布雷病",
      }],
    },
    isLoading: false,
  });
  hooks.useDiseaseComparisonPreview.mockReturnValue(comparisonMutation ?? {
    data: undefined,
    error: null,
    isPending: false,
    mutateAsync: vi.fn().mockResolvedValue(undefined),
    reset: vi.fn(),
  });
  return { linkDocument, unlinkDocument, loadMoreProfiles, refreshCurrentProfile, profilesState };
}

function findingPageItem(index: number) {
  return {
    ...finding,
    id: `run-1:key_findings:finding-${index}`,
    text: `Finding ${index}`,
  };
}

function detailWithFindingCount(count: number) {
  return {
    ...detail,
    section_counts: { key_findings: count },
    sections: [{
      section: "key_findings" as const,
      count,
      items: Array.from({ length: Math.min(5, count) }, (_, index) => findingPageItem(index)),
    }],
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, resolve, reject };
}

function comparisonPreview(title: string): ComparisonPreview {
  const notReported = {
    value: "Not reported",
    support_status: "not_reported" as const,
    evidence: [],
    evidence_total: 0,
    evidence_truncated: false,
    warnings: [],
  };
  return {
    concept_id: "mesh:D000795",
    documents: [{
      document_id: title,
      title,
      document_kind: "research_paper",
      document_date: "2026-01-01",
      open_filename: `${title}.pdf`,
      analysis_run_id: `${title}-run`,
      parsed_source_hash: `${title}-hash`,
      coverage_status: "complete",
      coverage: {
        status: "complete",
        selected_chunks: 1,
        total_chunks: 1,
        included_sections: ["methods"],
        omitted_sections: [],
      },
      methods: {
        design: notReported,
        population: notReported,
        human_animal_in_vitro: notReported,
        sample_size: notReported,
        comparator: notReported,
      },
      findings: [],
      findings_total: 0,
      findings_truncated: false,
      limitations: [],
      limitations_total: 0,
      limitations_truncated: false,
    }],
    discussion_questions: [],
    warnings: [],
  };
}

describe("DiseaseProfilePanel", () => {
  beforeEach(() => vi.clearAllMocks());

  afterEach(() => cleanup());

  it("shows source document and quote in the evidence drawer", async () => {
    const user = userEvent.setup();
    configure();
    render(<DiseaseProfilePanel workspaceId="workspace-1" onOpenVisitPrep={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: "Key findings 1" }));
    await user.click(screen.getByRole("button", { name: "View source (1)" }));

    expect(screen.getByRole("dialog", { name: "Evidence source" })).toBeInTheDocument();
    const drawer = screen.getByRole("dialog", { name: "Evidence source" });
    const quote = drawer.querySelector(".disease-source-quote");
    expect(quote).not.toBeNull();
    expect(within(quote as HTMLElement).getByText("fabry-study.pdf")).toBeInTheDocument();
    expect(within(drawer).getByText("Page 4")).toBeInTheDocument();
    expect(within(drawer).getByText("The measured outcome changed after the intervention.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Close source details" }));
    expect(screen.queryByRole("dialog", { name: "Evidence source" })).not.toBeInTheDocument();
  });

  it("links an unassigned document through the local concept picker", async () => {
    const user = userEvent.setup();
    const { linkDocument } = configure({
      unassigned: [{
        document_id: "document-2",
        title: "unassigned.pdf",
        document_kind: "research_paper",
        language: "zh",
        document_date: "",
        medical_confidence: 0.9,
        classifier_version: "medical-rules-v1",
        warnings: [],
      }],
    });
    render(<DiseaseProfilePanel workspaceId="workspace-1" onOpenVisitPrep={vi.fn()} />);

    const search = screen.getByLabelText("Search disease for unassigned.pdf");
    await user.type(search, "法布雷病");
    await user.click(screen.getByRole("button", { name: /matched "法布雷病"/ }));
    await user.click(screen.getByRole("button", { name: "Link to profile" }));

    expect(linkDocument).toHaveBeenCalledWith({
      documentId: "document-2",
      conceptId: "mesh:D000795",
      matchedAlias: "法布雷病",
    });
  });

  it("removes a linked document without exposing private notes", async () => {
    const user = userEvent.setup();
    const { unlinkDocument } = configure();
    render(<DiseaseProfilePanel workspaceId="workspace-1" onOpenVisitPrep={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: "Remove fabry-study.pdf from profile" }));

    expect(unlinkDocument).toHaveBeenCalledWith({
      documentId: "document-1",
      conceptId: "mesh:D000795",
    });
    expect(screen.queryByText("private note")).not.toBeInTheDocument();
  });

  it("loads the next disease profile page without replacing the current list", async () => {
    const user = userEvent.setup();
    const { loadMoreProfiles } = configure({ hasMoreProfiles: true });
    render(<DiseaseProfilePanel workspaceId="workspace-1" onOpenVisitPrep={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: "Load more profiles" }));

    expect(loadMoreProfiles).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: /Fabry Disease/ })).toBeInTheDocument();
  });

  it("loads more linked source documents without replacing the profile", async () => {
    const user = userEvent.setup();
    const loadMoreDocuments = vi.fn().mockResolvedValue(undefined);
    const linkedDocuments = [
      ...detail.documents,
      {
        document_id: "document-2",
        title: "second-fabry-study.pdf",
        document_kind: "guideline",
        language: "en",
        document_date: "2026-02-01",
        parsed_source_hash: "parsed-2",
        current_analysis_run_id: "run-2",
        source_status: "current" as const,
        warnings: [],
      },
    ];
    configure({
      detailValue: { ...detail, document_count: 2 },
      linkedDocuments,
      hasMoreDocuments: true,
      loadMoreDocuments,
    });

    render(<DiseaseProfilePanel workspaceId="workspace-1" onOpenVisitPrep={vi.fn()} />);

    expect(screen.getByText("second-fabry-study.pdf")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Load more linked documents" }));

    expect(loadMoreDocuments).toHaveBeenCalledTimes(1);
  });

  it("compares two selected current documents in the chosen order", async () => {
    const user = userEvent.setup();
    const mutateAsync = vi.fn().mockResolvedValue(undefined);
    const linkedDocuments = [
      ...detail.documents,
      {
        document_id: "document-2",
        title: "second-fabry-study.pdf",
        document_kind: "guideline",
        language: "en",
        document_date: "2026-02-01",
        parsed_source_hash: "parsed-2",
        current_analysis_run_id: "run-2",
        source_status: "current" as const,
        warnings: [],
      },
    ];
    configure({
      detailValue: { ...detail, document_count: 2 },
      linkedDocuments,
      comparisonMutation: {
        data: undefined,
        error: null,
        isPending: false,
        mutateAsync,
        reset: vi.fn(),
      },
    });

    render(<DiseaseProfilePanel workspaceId="workspace-1" onOpenVisitPrep={vi.fn()} />);

    await user.click(screen.getByRole("checkbox", { name: "Select fabry-study.pdf for comparison" }));
    await user.click(screen.getByRole("checkbox", { name: "Select second-fabry-study.pdf for comparison" }));
    await user.click(screen.getByRole("button", { name: "Compare selected documents" }));

    expect(mutateAsync).toHaveBeenCalledWith({
      documents: [
        {
          document_id: "document-1",
          expected_parsed_source_hash: "parsed-1",
          expected_analysis_run_id: "run-1",
        },
        {
          document_id: "document-2",
          expected_parsed_source_hash: "parsed-2",
          expected_analysis_run_id: "run-2",
        },
      ],
      language: "en",
    });
  });

  it("ignores a late comparison response after the selection changes", async () => {
    const user = userEvent.setup();
    const first = deferred<ComparisonPreview>();
    const second = deferred<ComparisonPreview>();
    const mutateAsync = vi.fn()
      .mockImplementationOnce(() => first.promise)
      .mockImplementationOnce(() => second.promise);
    const linkedDocuments = [
      ...detail.documents,
      {
        document_id: "document-2",
        title: "second-fabry-study.pdf",
        document_kind: "guideline",
        language: "en",
        document_date: "2026-02-01",
        parsed_source_hash: "parsed-2",
        current_analysis_run_id: "run-2",
        source_status: "current" as const,
        warnings: [],
      },
      {
        document_id: "document-3",
        title: "third-fabry-study.pdf",
        document_kind: "research_paper",
        language: "en",
        document_date: "2026-03-01",
        parsed_source_hash: "parsed-3",
        current_analysis_run_id: "run-3",
        source_status: "current" as const,
        warnings: [],
      },
    ];
    configure({
      detailValue: { ...detail, document_count: 3 },
      linkedDocuments,
      comparisonMutation: {
        data: undefined,
        error: null,
        isPending: false,
        mutateAsync,
        reset: vi.fn(),
      },
    });

    render(<DiseaseProfilePanel workspaceId="workspace-1" onOpenVisitPrep={vi.fn()} />);
    await user.click(screen.getByRole("checkbox", { name: "Select fabry-study.pdf for comparison" }));
    await user.click(screen.getByRole("checkbox", { name: "Select second-fabry-study.pdf for comparison" }));
    await user.click(screen.getByRole("button", { name: "Compare selected documents" }));

    await user.click(screen.getByRole("checkbox", { name: "Select second-fabry-study.pdf for comparison" }));
    await user.click(screen.getByRole("checkbox", { name: "Select third-fabry-study.pdf for comparison" }));
    await user.click(screen.getByRole("button", { name: "Compare selected documents" }));
    expect(mutateAsync).toHaveBeenCalledTimes(2);

    first.resolve(comparisonPreview("stale-ab"));
    await waitFor(() => {
      expect(screen.queryByRole("heading", { name: "Compare selected sources" })).not.toBeInTheDocument();
    });

    second.resolve(comparisonPreview("current-ac"));
    await waitFor(() => {
      expect(screen.getByText("current-ac")).toBeInTheDocument();
      expect(screen.queryByText("stale-ab")).not.toBeInTheDocument();
    });
  });

  it("refreshes changed comparison sources before allowing a new comparison", async () => {
    const user = userEvent.setup();
    const sourceChanged = new axios.AxiosError("source changed");
    sourceChanged.response = {
      status: 409,
      statusText: "Conflict",
      headers: {},
      config: {} as never,
      data: { code: "comparison_source_changed" },
    };
    const mutateAsync = vi.fn()
      .mockRejectedValueOnce(sourceChanged)
      .mockResolvedValueOnce(comparisonPreview("refreshed-comparison"));
    const linkedDocuments = [
      ...detail.documents,
      {
        document_id: "document-2",
        title: "second-fabry-study.pdf",
        document_kind: "guideline",
        language: "en",
        document_date: "2026-02-01",
        parsed_source_hash: "parsed-2",
        current_analysis_run_id: "run-2",
        source_status: "current" as const,
        warnings: [],
      },
    ];
    const configured = configure({
      detailValue: { ...detail, document_count: 2 },
      linkedDocuments,
      comparisonMutation: {
        data: undefined,
        error: null,
        isPending: false,
        mutateAsync,
        reset: vi.fn(),
      },
    });
    const refreshGate = deferred<void>();
    configured.refreshCurrentProfile.mockImplementation(async () => {
      configured.profilesState.linkedDocuments = [
        {
          ...detail.documents[0],
          current_analysis_run_id: "run-3",
        },
        linkedDocuments[1],
      ];
      configured.profilesState.detail = {
        ...detail,
        document_count: 2,
        documents: configured.profilesState.linkedDocuments,
      };
      await refreshGate.promise;
    });

    render(<DiseaseProfilePanel workspaceId="workspace-1" onOpenVisitPrep={vi.fn()} />);
    await user.click(screen.getByRole("checkbox", { name: "Select fabry-study.pdf for comparison" }));
    await user.click(screen.getByRole("checkbox", { name: "Select second-fabry-study.pdf for comparison" }));
    await user.click(screen.getByRole("button", { name: "Compare selected documents" }));

    expect(await screen.findByText("The selected source data changed. Refresh the profile before comparing again.")).toBeInTheDocument();
    const refreshButton = screen.getByRole("button", { name: "Refresh sources" });
    await user.click(refreshButton);
    expect(screen.getByRole("button", { name: "Refreshing sources..." })).toBeInTheDocument();
    refreshGate.resolve();
    await waitFor(() => {
      expect(configured.refreshCurrentProfile).toHaveBeenCalledTimes(1);
      expect(screen.queryByRole("button", { name: "Refresh sources" })).not.toBeInTheDocument();
    });
    expect(screen.getByText("0/5 selected")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Sources refreshed. Select two to five documents again.");

    await user.click(screen.getByRole("checkbox", { name: "Select fabry-study.pdf for comparison" }));
    await user.click(screen.getByRole("checkbox", { name: "Select second-fabry-study.pdf for comparison" }));

    await user.click(screen.getByRole("button", { name: "Compare selected documents" }));
    await waitFor(() => expect(mutateAsync).toHaveBeenCalledTimes(2));
    expect(mutateAsync.mock.calls[1][0]).toMatchObject({
      documents: [
        {
          document_id: "document-1",
          expected_parsed_source_hash: "parsed-1",
          expected_analysis_run_id: "run-3",
        },
        {
          document_id: "document-2",
          expected_parsed_source_hash: "parsed-2",
          expected_analysis_run_id: "run-2",
        },
      ],
    });
    expect(await screen.findByText("refreshed-comparison")).toBeInTheDocument();
  });

  it("hides a comparison when the current analysis run changes with the same parse hash", async () => {
    const user = userEvent.setup();
    const response = deferred<ComparisonPreview>();
    const mutateAsync = vi.fn().mockReturnValue(response.promise);
    const linkedDocuments = [
      ...detail.documents,
      {
        document_id: "document-2",
        title: "second-fabry-study.pdf",
        document_kind: "guideline",
        language: "en",
        document_date: "2026-02-01",
        parsed_source_hash: "parsed-2",
        current_analysis_run_id: "run-2",
        source_status: "current" as const,
        warnings: [],
      },
    ];
    const configured = configure({
      detailValue: { ...detail, document_count: 2 },
      linkedDocuments,
      comparisonMutation: {
        data: undefined,
        error: null,
        isPending: false,
        mutateAsync,
        reset: vi.fn(),
      },
    });
    const view = render(<DiseaseProfilePanel workspaceId="workspace-1" onOpenVisitPrep={vi.fn()} />);
    await user.click(screen.getByRole("checkbox", { name: "Select fabry-study.pdf for comparison" }));
    await user.click(screen.getByRole("checkbox", { name: "Select second-fabry-study.pdf for comparison" }));
    await user.click(screen.getByRole("button", { name: "Compare selected documents" }));

    configured.profilesState.linkedDocuments = [
      {
        ...detail.documents[0],
        current_analysis_run_id: "run-4",
      },
      linkedDocuments[1],
    ];
    configured.profilesState.detail = {
      ...detail,
      document_count: 2,
      documents: configured.profilesState.linkedDocuments,
    };
    view.rerender(<DiseaseProfilePanel workspaceId="workspace-1" onOpenVisitPrep={vi.fn()} />);
    response.resolve(comparisonPreview("stale-run-comparison"));

    await waitFor(() => {
      expect(screen.queryByRole("heading", { name: "Compare selected sources" })).not.toBeInTheDocument();
      expect(screen.queryByText("stale-run-comparison")).not.toBeInTheDocument();
    });
  });

  it("keeps the refresh action when the profile detail refresh fails", async () => {
    const user = userEvent.setup();
    const sourceChanged = new axios.AxiosError("source changed");
    sourceChanged.response = {
      status: 409,
      statusText: "Conflict",
      headers: {},
      config: {} as never,
      data: { code: "comparison_source_changed" },
    };
    const mutateAsync = vi.fn().mockRejectedValue(sourceChanged);
    const linkedDocuments = [
      ...detail.documents,
      {
        document_id: "document-2",
        title: "second-fabry-study.pdf",
        document_kind: "guideline",
        language: "en",
        document_date: "2026-02-01",
        parsed_source_hash: "parsed-2",
        current_analysis_run_id: "run-2",
        source_status: "current" as const,
        warnings: [],
      },
    ];
    const configured = configure({
      detailValue: { ...detail, document_count: 2 },
      linkedDocuments,
      comparisonMutation: {
        data: undefined,
        error: null,
        isPending: false,
        mutateAsync,
        reset: vi.fn(),
      },
    });
    configured.refreshCurrentProfile.mockRejectedValue(new Error("detail failed"));

    render(<DiseaseProfilePanel workspaceId="workspace-1" onOpenVisitPrep={vi.fn()} />);
    await user.click(screen.getByRole("checkbox", { name: "Select fabry-study.pdf for comparison" }));
    await user.click(screen.getByRole("checkbox", { name: "Select second-fabry-study.pdf for comparison" }));
    await user.click(screen.getByRole("button", { name: "Compare selected documents" }));
    await screen.findByText("The selected source data changed. Refresh the profile before comparing again.");
    await user.click(screen.getByRole("button", { name: "Refresh sources" }));

    expect(await screen.findByText("Could not refresh the disease profile.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Refresh sources" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Compare selected sources" })).not.toBeInTheDocument();
  });

  it("keeps the refresh action when a loaded document page refresh fails", async () => {
    const user = userEvent.setup();
    const sourceChanged = new axios.AxiosError("source changed");
    sourceChanged.response = {
      status: 409,
      statusText: "Conflict",
      headers: {},
      config: {} as never,
      data: { code: "comparison_source_changed" },
    };
    const mutateAsync = vi.fn().mockRejectedValue(sourceChanged);
    const linkedDocuments = [
      ...detail.documents,
      {
        document_id: "document-2",
        title: "second-fabry-study.pdf",
        document_kind: "guideline",
        language: "en",
        document_date: "2026-02-01",
        parsed_source_hash: "parsed-2",
        current_analysis_run_id: "run-2",
        source_status: "current" as const,
        warnings: [],
      },
    ];
    const configured = configure({
      detailValue: { ...detail, document_count: 2 },
      linkedDocuments,
      comparisonMutation: {
        data: undefined,
        error: null,
        isPending: false,
        mutateAsync,
        reset: vi.fn(),
      },
    });
    configured.refreshCurrentProfile.mockRejectedValue(new Error("page failed"));

    render(<DiseaseProfilePanel workspaceId="workspace-1" onOpenVisitPrep={vi.fn()} />);
    await user.click(screen.getByRole("checkbox", { name: "Select fabry-study.pdf for comparison" }));
    await user.click(screen.getByRole("checkbox", { name: "Select second-fabry-study.pdf for comparison" }));
    await user.click(screen.getByRole("button", { name: "Compare selected documents" }));
    await screen.findByText("The selected source data changed. Refresh the profile before comparing again.");
    await user.click(screen.getByRole("button", { name: "Refresh sources" }));

    expect(await screen.findByText("Could not refresh the disease profile.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Refresh sources" })).toBeInTheDocument();
    expect(screen.queryByText("Sources refreshed. Select two to five documents again.")).not.toBeInTheDocument();
  });

  it("clears selections after refresh so unseen pages cannot retain stale document ids", async () => {
    const user = userEvent.setup();
    const sourceChanged = new axios.AxiosError("source changed");
    sourceChanged.response = {
      status: 409,
      statusText: "Conflict",
      headers: {},
      config: {} as never,
      data: { code: "comparison_source_changed" },
    };
    const mutateAsync = vi.fn().mockRejectedValue(sourceChanged);
    const linkedDocuments = [
      ...detail.documents,
      ...Array.from({ length: 20 }, (_, index) => ({
        document_id: `document-${index + 2}`,
        title: `fabry-study-${index + 2}.pdf`,
        document_kind: "guideline",
        language: "en",
        document_date: "2026-02-01",
        parsed_source_hash: `parsed-${index + 2}`,
        current_analysis_run_id: `run-${index + 2}`,
        source_status: "current" as const,
        warnings: [],
      })),
    ];
    const configured = configure({
      detailValue: { ...detail, document_count: 2 },
      linkedDocuments,
      comparisonMutation: {
        data: undefined,
        error: null,
        isPending: false,
        mutateAsync,
        reset: vi.fn(),
      },
    });
    configured.refreshCurrentProfile.mockImplementation(async () => {
      configured.profilesState.linkedDocuments = [
        ...linkedDocuments.slice(0, 20),
      ];
      configured.profilesState.detail = {
        ...detail,
        document_count: 21,
        documents: configured.profilesState.linkedDocuments as typeof detail.documents,
      };
      return configured.profilesState.detail;
    });

    render(<DiseaseProfilePanel workspaceId="workspace-1" onOpenVisitPrep={vi.fn()} />);
    await user.click(screen.getByRole("checkbox", { name: "Select fabry-study.pdf for comparison" }));
    await user.click(screen.getByRole("checkbox", { name: "Select fabry-study-21.pdf for comparison" }));
    await user.click(screen.getByRole("button", { name: "Compare selected documents" }));
    await screen.findByText("The selected source data changed. Refresh the profile before comparing again.");
    await user.click(screen.getByRole("button", { name: "Refresh sources" }));

    await waitFor(() => {
      expect(screen.getByText("0/5 selected")).toBeInTheDocument();
      expect(screen.getByRole("status")).toHaveTextContent("Sources refreshed. Select two to five documents again.");
      expect(screen.queryByRole("checkbox", { name: "Select fabry-study-21.pdf for comparison" })).not.toBeInTheDocument();
    });
  });

  it("loads more unassigned documents and keeps the total count", async () => {
    const user = userEvent.setup();
    const loadMoreUnassigned = vi.fn().mockResolvedValue(undefined);
    configure({
      unassigned: [{
        document_id: "document-2",
        title: "unassigned.pdf",
        document_kind: "research_paper",
        language: "en",
        document_date: "",
        medical_confidence: 0.9,
        classifier_version: "medical-rules-v1",
        warnings: [],
      }],
      unassignedTotal: 21,
      hasMoreUnassigned: true,
      loadMoreUnassigned,
    });

    render(<DiseaseProfilePanel workspaceId="workspace-1" onOpenVisitPrep={vi.fn()} />);

    expect(screen.getByText("21")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Load more documents" }));

    expect(loadMoreUnassigned).toHaveBeenCalledTimes(1);
  });

  it("appends a single section page even when the API has no next cursor", async () => {
    const user = userEvent.setup();
    const pageItems = Array.from({ length: 10 }, (_, index) => findingPageItem(index));
    configure({ detailValue: detailWithFindingCount(10) });
    hooks.useDiseaseProfileItems.mockImplementation(
      (_workspaceId: string, _conceptId: string, _section: string, _cursor: string | null, enabled: boolean) => ({
        data: enabled ? { section: "key_findings", items: pageItems, next_cursor: null } : undefined,
        isLoading: false,
      }),
    );

    render(<DiseaseProfilePanel workspaceId="workspace-1" onOpenVisitPrep={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Key findings 10" }));
    await user.click(screen.getByRole("button", { name: "Load more" }));

    expect(screen.getAllByRole("article")).toHaveLength(10);
    expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
  });

  it("appends and finishes on the last section page without duplicates", async () => {
    const user = userEvent.setup();
    const firstPage = Array.from({ length: 20 }, (_, index) => findingPageItem(index));
    const lastPage = Array.from({ length: 5 }, (_, index) => findingPageItem(index + 20));
    configure({ detailValue: detailWithFindingCount(25) });
    hooks.useDiseaseProfileItems.mockImplementation(
      (_workspaceId: string, _conceptId: string, _section: string, cursor: string | null, enabled: boolean) => ({
        data: enabled
          ? {
              section: "key_findings",
              items: cursor === "20" ? lastPage : firstPage,
              next_cursor: cursor === "20" ? null : "20",
            }
          : undefined,
        isLoading: false,
      }),
    );

    render(<DiseaseProfilePanel workspaceId="workspace-1" onOpenVisitPrep={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Key findings 25" }));
    await user.click(screen.getByRole("button", { name: "Load more" }));
    expect(screen.getAllByRole("article")).toHaveLength(20);

    await user.click(screen.getByRole("button", { name: "Load more" }));
    expect(screen.getAllByRole("article")).toHaveLength(25);
    expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
    expect(screen.getAllByText(/^Finding /)).toHaveLength(25);
  });
});
