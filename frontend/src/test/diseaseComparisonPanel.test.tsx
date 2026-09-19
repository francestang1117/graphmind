import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import DiseaseComparisonPanel from "../components/disease-profile/DiseaseComparisonPanel";
import type { ComparisonEvidence, ComparisonMethod, ComparisonPreview } from "../services/api";

const evidence: ComparisonEvidence = {
  document_id: "document-1",
  analysis_run_id: "run-1",
  evidence_id: "EVIDENCE-1",
  quote: "Adults with the condition were followed for 12 weeks.",
  section_type: "methods",
  section_title: "Methods",
  page_start: 7,
  page_end: 7,
  quote_truncated: false,
};

const secondEvidence: ComparisonEvidence = {
  ...evidence,
  evidence_id: "EVIDENCE-2",
  quote: "The follow-up assessment was reported on the next page.",
  page_start: 8,
  page_end: 8,
  quote_truncated: true,
};

const supportedMethod: ComparisonMethod = {
  value: "Human participants",
  support_status: "supported",
  evidence: [evidence, secondEvidence],
  warnings: [],
};

const notReportedMethod: ComparisonMethod = {
  value: "The selected analysis evidence did not report this field.",
  support_status: "not_reported",
  evidence: [],
  warnings: [],
};

function preview(): ComparisonPreview {
  return {
    concept_id: "mesh:D000795",
    documents: [
      {
        document_id: "document-1",
        title: "Fabry cohort study.pdf",
        document_kind: "research_paper",
        document_date: "2026-01-01",
        open_filename: "stored-document-1.pdf",
        analysis_run_id: "run-1",
        parsed_source_hash: "parsed-1",
        coverage_status: "partial",
        coverage: {
          status: "partial",
          selected_chunks: 8,
          total_chunks: 12,
          included_sections: ["methods", "results"],
          omitted_sections: ["discussion"],
        },
        methods: {
          design: supportedMethod,
          population: supportedMethod,
          human_animal_in_vitro: supportedMethod,
          sample_size: supportedMethod,
          comparator: notReportedMethod,
        },
        findings: Array.from({ length: 10 }, (_, index) => ({
          id: `finding-${index}`,
          statement: `Reported finding ${index + 1}`,
          explanation: "A source-bound finding.",
          evidence: [evidence],
          warnings: [],
        })),
        findings_total: 12,
        findings_truncated: true,
        limitations: [],
        limitations_total: 0,
        limitations_truncated: false,
      },
      {
        document_id: "document-2",
        title: "Fabry guideline.pdf",
        document_kind: "guideline",
        document_date: "2026-02-01",
        open_filename: "stored-document-2.pdf",
        analysis_run_id: "run-2",
        parsed_source_hash: "parsed-2",
        coverage_status: "complete",
        coverage: {
          status: "complete",
          selected_chunks: 10,
          total_chunks: 10,
          included_sections: ["methods", "recommendations"],
          omitted_sections: [],
        },
        methods: {
          design: notReportedMethod,
          population: notReportedMethod,
          human_animal_in_vitro: notReportedMethod,
          sample_size: notReportedMethod,
          comparator: notReportedMethod,
        },
        findings: [],
        findings_total: 0,
        findings_truncated: false,
        limitations: [],
        limitations_total: 0,
        limitations_truncated: false,
      },
    ],
    discussion_questions: [],
    warnings: ["comparison_coverage_partial"],
  };
}

describe("DiseaseComparisonPanel", () => {
  it("shows per-document coverage, not-reported status, truncation, and source evidence", async () => {
    const user = userEvent.setup();
    render(<DiseaseComparisonPanel preview={preview()} workspaceId="workspace-1" />);

    expect(screen.getByText("Fabry cohort study.pdf")).toBeInTheDocument();
    expect(screen.getByText("Coverage partial · 8/12 chunks")).toBeInTheDocument();
    expect(screen.getByText("Coverage complete · 10/10 chunks")).toBeInTheDocument();
    expect(screen.getAllByText("Not reported").length).toBeGreaterThan(0);
    expect(screen.getByText(/Showing 10 of 12 findings/)).toBeInTheDocument();

    await user.click(screen.getAllByRole("button", { name: "View evidence (2)" })[0]);

    const drawer = screen.getByRole("dialog", { name: "Comparison evidence source" });
    expect(drawer).toHaveTextContent("Fabry cohort study.pdf");
    expect(drawer).toHaveTextContent("Page 7");
    expect(drawer).toHaveTextContent("Run run-1");
    expect(drawer).toHaveTextContent("Adults with the condition were followed for 12 weeks.");
    expect(drawer).toHaveTextContent("Evidence 1 / 2");
    expect(screen.getByRole("link", { name: /Open source document/ })).toHaveAttribute(
      "href",
      expect.stringContaining("stored-document-1.pdf"),
    );

    await user.click(screen.getByRole("button", { name: "Next evidence" }));
    expect(drawer).toHaveTextContent("Page 8");
    expect(drawer).toHaveTextContent("The follow-up assessment was reported on the next page.");
    expect(drawer).toHaveTextContent("Evidence EVIDENCE-2");
    expect(drawer).toHaveTextContent("Evidence 2 / 2");
    expect(drawer).toHaveTextContent("Excerpt shortened for preview");
    expect(screen.getByRole("button", { name: "Next evidence" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Previous evidence" }));
    expect(drawer).toHaveTextContent("Page 7");

    await user.click(screen.getByRole("button", { name: "Close comparison evidence" }));
    expect(screen.queryByRole("dialog", { name: "Comparison evidence source" })).not.toBeInTheDocument();
  });
});
