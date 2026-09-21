import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import DiseaseSourceDrawer from "../components/disease-profile/DiseaseSourceDrawer";
import type { DiseaseProfileItem } from "../services/api";

const item = {
  id: "question-1",
  item_type: "question",
  section: "clinician_questions",
  document_title: "paper-a.pdf",
  document_kind: "research_paper",
  document_date: "2026-01-01",
  source_status: "current",
  question: "Which participants were included?",
  evidence_total: 2,
  evidence_truncated: false,
  evidence: [
    {
      source_type: "document_evidence",
      evidence_id: "EVIDENCE_001",
      document_id: "doc-a",
      document_title: "paper-a.pdf",
      document_date: "2026-01-01",
      analysis_run_id: "run-a",
      parsed_source_hash: "parsed-a",
      section_type: "methods",
      section_title: "Methods",
      page_start: 1,
      page_end: 1,
      quote: "Quote from paper A.",
      source: "",
      external_id: "",
      source_url: "",
      retraction_status: "unknown",
      flagged: false,
      warnings: [],
    },
    {
      source_type: "document_evidence",
      evidence_id: "EVIDENCE_001",
      document_id: "doc-b",
      document_title: "paper-b.pdf",
      document_date: "2026-02-01",
      analysis_run_id: "run-b",
      parsed_source_hash: "parsed-b",
      section_type: "methods",
      section_title: "Methods",
      page_start: 1,
      page_end: 1,
      quote: "Quote from paper B.",
      source: "",
      external_id: "",
      source_url: "",
      retraction_status: "unknown",
      flagged: false,
      warnings: [],
    },
  ],
  warnings: [],
} as unknown as DiseaseProfileItem;

describe("DiseaseSourceDrawer evidence identity", () => {
  afterEach(cleanup);

  it("renders same evidence IDs from different documents independently", () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});

    render(<DiseaseSourceDrawer item={item} onClose={vi.fn()} />);

    expect(screen.getByText("Quote from paper A.")).toBeInTheDocument();
    expect(screen.getByText("Quote from paper B.")).toBeInTheDocument();
    expect(
      consoleError.mock.calls.flat().join(" "),
    ).not.toContain("Encountered two children with the same key");

    consoleError.mockRestore();
  });
});
