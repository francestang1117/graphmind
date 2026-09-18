import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import DiseaseProfilePanel from "../components/DiseaseProfilePanel";
import type { UnassignedDiseaseDocument } from "../services/api";

const hooks = vi.hoisted(() => ({
  useDiseaseProfiles: vi.fn(),
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
    source_status: "current",
    warnings: [],
  }],
  sections: [{ section: "key_findings", count: 1, items: [finding] }],
};

function configure({
  profiles = [summary],
  selectedConceptId = "mesh:D000795",
  unassigned = [],
  hasMoreProfiles = false,
}: {
  profiles?: typeof summary[];
  selectedConceptId?: string | null;
  unassigned?: UnassignedDiseaseDocument[];
  hasMoreProfiles?: boolean;
} = {}) {
  const linkDocument = vi.fn().mockResolvedValue(undefined);
  const unlinkDocument = vi.fn().mockResolvedValue(undefined);
  const loadMoreProfiles = vi.fn().mockResolvedValue(undefined);
  hooks.useDiseaseProfiles.mockReturnValue({
    list: profiles,
    hasMoreProfiles,
    loadingMoreProfiles: false,
    loadMoreProfiles,
    selectedConceptId,
    listQuery: { isLoading: false, error: null, refetch: vi.fn() },
    detail,
    detailQuery: { isLoading: false, error: null, refetch: vi.fn() },
    unassigned,
    unassignedQuery: { isLoading: false, error: null, refetch: vi.fn() },
    linkDocument,
    linking: false,
    unlinkDocument,
    unlinking: false,
  });
  hooks.useDiseaseProfileItems.mockReturnValue({ data: undefined, isLoading: false });
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
  return { linkDocument, unlinkDocument, loadMoreProfiles };
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
});
