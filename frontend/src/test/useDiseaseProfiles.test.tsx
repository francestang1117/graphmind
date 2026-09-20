import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useDiseaseProfiles } from "../hooks/useDiseaseProfiles";

const api = vi.hoisted(() => ({
  createDiseaseLink: vi.fn(),
  deleteDiseaseLink: vi.fn(),
  getDiseaseProfile: vi.fn(),
  getDiseaseProfileDocuments: vi.fn(),
  getDiseaseProfileExternalSourceDocuments: vi.fn(),
  getDiseaseProfileItems: vi.fn(),
  listDiseaseProfiles: vi.fn(),
  listUnassignedDiseaseDocuments: vi.fn(),
  previewDiseaseProfileComparison: vi.fn(),
  searchDiseaseConcepts: vi.fn(),
}));

vi.mock("../services/api", () => api);

const document = {
  document_id: "document-1",
  title: "fabry-study.pdf",
  document_kind: "research_paper",
  language: "en",
  document_date: "2026-01-01",
  parsed_source_hash: "parsed-1",
  current_analysis_run_id: "run-1",
  source_status: "current" as const,
  warnings: [],
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
  last_updated_at: "2026-09-20T00:00:00+00:00",
  section_counts: {},
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
    comparator_not_reported_count: 0,
    human_study_count: 1,
    animal_study_count: 0,
    in_vitro_study_count: 0,
    unknown_study_population_count: 0,
    sample_size_reported_count: 0,
    sample_size_not_reported_count: 1,
    unknown_date_count: 0,
  },
  documents: [document],
  documents_next_cursor: null as string | null,
  sections: [],
};

function wrapper({ children }: PropsWithChildren) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function configureApi(overrides: { detailDocuments?: typeof detail.documents; nextCursor?: string | null } = {}) {
  const detailValue = {
    ...detail,
    documents: overrides.detailDocuments ?? detail.documents,
    documents_next_cursor: overrides.nextCursor ?? null,
  };
  api.listDiseaseProfiles.mockResolvedValue({ items: [summary], next_cursor: null });
  api.getDiseaseProfile.mockResolvedValue(detailValue);
  api.getDiseaseProfileDocuments.mockResolvedValue({ items: [], next_cursor: null });
  api.getDiseaseProfileExternalSourceDocuments.mockResolvedValue({ items: [], next_cursor: null });
  api.getDiseaseProfileItems.mockResolvedValue({ section: "key_findings", items: [], next_cursor: null });
  api.listUnassignedDiseaseDocuments.mockResolvedValue({ items: [], total: 0, next_cursor: null });
  api.searchDiseaseConcepts.mockResolvedValue({ items: [] });
  api.createDiseaseLink.mockResolvedValue(undefined);
  api.deleteDiseaseLink.mockResolvedValue(undefined);
  api.previewDiseaseProfileComparison.mockResolvedValue(undefined);
}

describe("useDiseaseProfiles refreshCurrentProfile", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("propagates a detail refetch failure instead of returning cached data", async () => {
    configureApi();
    const { result } = renderHook(
      () => useDiseaseProfiles("workspace-1", "mesh:D000795"),
      { wrapper },
    );
    await waitFor(() => expect(result.current.detail).not.toBeNull());

    api.getDiseaseProfile.mockRejectedValueOnce(new Error("detail failed"));

    await expect(act(async () => {
      await result.current.refreshCurrentProfile();
    })).rejects.toThrow("detail failed");
    expect(result.current.detail).toEqual(detail);
  });

  it("propagates a loaded document page refetch failure", async () => {
    const secondDocument = {
      ...document,
      document_id: "document-2",
      title: "second-fabry-study.pdf",
      parsed_source_hash: "parsed-2",
      current_analysis_run_id: "run-2",
    };
    configureApi({ nextCursor: "cursor-1" });
    api.getDiseaseProfileDocuments.mockResolvedValueOnce({
      items: [secondDocument],
      next_cursor: null,
    });
    const { result } = renderHook(
      () => useDiseaseProfiles("workspace-1", "mesh:D000795"),
      { wrapper },
    );
    await waitFor(() => expect(result.current.hasMoreDocuments).toBe(true));
    await act(async () => {
      await result.current.loadMoreDocuments();
    });
    expect(api.getDiseaseProfileDocuments).toHaveBeenCalledWith(
      "mesh:D000795",
      "workspace-1",
      { limit: 20, cursor: "cursor-1" },
    );
    await waitFor(() => expect(result.current.linkedDocuments).toHaveLength(2));

    api.getDiseaseProfileDocuments.mockRejectedValueOnce(new Error("page failed"));

    await expect(act(async () => {
      await result.current.refreshCurrentProfile();
    })).rejects.toThrow("page failed");
  });
});
