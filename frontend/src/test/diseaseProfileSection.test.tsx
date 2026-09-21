import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import DiseaseProfileSection from "../components/disease-profile/DiseaseProfileSection";
import type { DiseaseProfileItem } from "../services/api";

const item: DiseaseProfileItem = {
  id: "finding-1",
  item_type: "finding",
  section: "key_findings",
  document_id: "document-1",
  document_ids: ["document-1"],
  document_title: "study.pdf",
  document_titles: ["study.pdf"],
  related_document_count: 1,
  related_documents_truncated: false,
  evidence_truncated: false,
  document_kind: "research_paper",
  document_date: "2026-01-01",
  analysis_run_id: "run-1",
  parsed_source_hash: "parsed-1",
  source_status: "current",
  title: "Reported finding",
  text: "The study reported a finding.",
  explanation: "The source describes the finding.",
  value: "",
  support_status: "supported",
  term: "",
  question: "",
  rationale: "",
  category: "",
  topic: "",
  source_kind: "",
  source_id: "",
  evidence_ids: [],
  evidence: [],
  evidence_total: 0,
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

function renderSection(overrides: Partial<DiseaseProfileItem> = {}) {
  return render(
    <DiseaseProfileSection
      name="key_findings"
      count={1}
      items={[{ ...item, ...overrides }]}
      expanded
      loading={false}
      hasMore={false}
      truncated={false}
      onToggle={vi.fn()}
      onLoadMore={vi.fn()}
      onOpenSource={vi.fn()}
    />,
  );
}

describe("DiseaseProfileSection source actions", () => {
  afterEach(cleanup);

  it("does not offer a source action for an item without evidence", () => {
    renderSection();

    expect(screen.queryByRole("button", { name: /view source/i })).not.toBeInTheDocument();
    expect(screen.getByText("No source attached")).toBeInTheDocument();
  });

  it("offers source details when evidence is available", () => {
    renderSection({
      evidence_ids: ["evidence-1"],
      evidence: [{
        source_type: "document_evidence",
        evidence_id: "evidence-1",
        document_id: "document-1",
        document_title: "study.pdf",
        document_date: "2026-01-01",
        parsed_source_hash: "parsed-1",
        section_type: "results",
        section_title: "Results",
        quote: "The study reported a finding.",
        source: "",
        external_id: "",
        source_url: "",
        retraction_status: "unknown",
        flagged: false,
        warnings: [],
      }],
    });

    expect(screen.getByRole("button", { name: /view source \(1\)/i })).toBeInTheDocument();
    expect(screen.queryByText("No source attached")).not.toBeInTheDocument();
  });

  it("discloses linked document and evidence truncation", () => {
    renderSection({
      document_ids: Array.from({ length: 20 }, (_, index) => `document-${index}`),
      related_document_count: 22,
      related_documents_truncated: true,
      evidence_truncated: true,
      evidence_total: 1,
      evidence_ids: ["evidence-1"],
      evidence: [{
        source_type: "document_evidence",
        evidence_id: "evidence-1",
        document_id: "document-1",
        document_title: "study.pdf",
        document_date: "2026-01-01",
        parsed_source_hash: "parsed-1",
        section_type: "results",
        section_title: "Results",
        quote: "The study reported a finding.",
        source: "",
        external_id: "",
        source_url: "",
        retraction_status: "unknown",
        flagged: false,
        warnings: [],
      }],
    });

    expect(screen.getByText("Showing the first 20 of 22 linked documents.")).toBeInTheDocument();
    expect(screen.getByText("Showing 1 of 1 evidence sources.")).toBeInTheDocument();
  });
});
