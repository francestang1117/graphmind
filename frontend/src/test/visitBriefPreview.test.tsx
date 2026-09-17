import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import VisitBriefPreview from "../components/visit-preparation/VisitBriefPreview";
import type { VisitBrief } from "../services/api";

const brief: VisitBrief = {
  id: "brief-1",
  workspace_id: "workspace-1",
  status: "active",
  language: "en",
  generated_at: "2026-09-16T00:00:00+00:00",
  data_cutoff_at: "2026-09-16T00:00:00+00:00",
  disclaimer: "This is a discussion aid, not a diagnosis or treatment recommendation.",
  items: [
    {
      id: "item-1",
      clinician_question_id: "question-1",
      document_id: "document-1",
      document_title: "example-paper.pdf",
      document_date: "2026-08-01",
      parsed_source_hash: "abcdef1234567890",
      analysis_run_id: "run-1",
      position: 0,
      question: "What did the study report?",
      rationale: "This clarifies the reported result.",
      user_note: "Only included when explicitly selected",
      evidence: [{
        evidence_id: "EVIDENCE_001",
        section_type: "results",
        section_title: "Results",
        page_start: 4,
        page_end: 4,
        quote: "The reported outcome changed.",
      }],
    },
  ],
};

describe("VisitBriefPreview", () => {
  afterEach(() => cleanup());

  it("renders selected snapshot content and exposes print/delete actions", () => {
    const onPrint = vi.fn();
    const onDelete = vi.fn();
    render(<VisitBriefPreview brief={brief} onPrint={onPrint} onDelete={onDelete} deleting={false} />);

    expect(screen.getByText("What did the study report?")).toBeInTheDocument();
    expect(screen.getByText("Source: example-paper.pdf")).toBeInTheDocument();
    expect(screen.getByText("The reported outcome changed.")).toBeInTheDocument();
    expect(document.querySelectorAll("details")).toHaveLength(0);
    expect(screen.getByText(/Snapshot created/)).toBeInTheDocument();
    expect(screen.getByText("Original evidence")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Print / Save PDF" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete visit brief" })).toBeInTheDocument();
  });

  it("keeps same-page evidence attributable to each document in the printable view", () => {
    const secondItem = {
      ...brief.items[0],
      id: "item-2",
      clinician_question_id: "question-2",
      document_id: "document-2",
      document_title: "second-paper.pdf",
      evidence: [{
        ...brief.items[0].evidence[0],
        evidence_id: "EVIDENCE_002",
        quote: "The second paper reported a different outcome.",
      }],
    };
    render(
      <VisitBriefPreview
        brief={{ ...brief, items: [brief.items[0], secondItem] }}
        onPrint={vi.fn()}
        onDelete={vi.fn()}
        deleting={false}
      />,
    );

    expect(screen.getByText("example-paper.pdf · Page 4 · Results")).toBeInTheDocument();
    expect(screen.getByText("second-paper.pdf · Page 4 · Results")).toBeInTheDocument();
    expect(screen.getByText("The second paper reported a different outcome.")).toBeInTheDocument();
  });
});
