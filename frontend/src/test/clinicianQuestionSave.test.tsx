import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import QuestionSuggestionList from "../components/upload/medical/QuestionSuggestionList";
import type { MedicalInsightReport, MedicalQuestionSuggestion } from "../services/api";

function suggestion(): MedicalQuestionSuggestion {
  return {
    id: "suggestion-1",
    question: "Which people were included in this study?",
    rationale: "The study population is important to discuss.",
    category: "applicability",
    topic: "study_population",
    source_kind: "study_methods",
    source_id: "population",
    evidence_ids: ["EVIDENCE_001"],
    interpretation_type: "inference",
  };
}

function report(): MedicalInsightReport {
  return {
    schema_version: "medical-insights-v3",
    document_kind: "research_paper",
    language: "en",
    overview: {
      title: "Example paper",
      summary: "A study summary.",
      study_type: "Research paper",
      evidence_ids: ["EVIDENCE_001"],
    },
    study_methods: undefined,
    key_findings: [],
    limitations: [],
    medical_terms: [],
    what_it_means: [],
    what_it_does_not_mean: [],
    applicability: [],
    future_research: [],
    question_suggestions: [suggestion()],
    questions_for_professional: [],
    coverage: undefined,
    warnings: [],
  };
}

describe("clinician question save control", () => {
  afterEach(() => cleanup());

  it("calls the save callback with only the structured suggestion", () => {
    const onSaveSuggestion = vi.fn();
    render(
      <QuestionSuggestionList
        report={report()}
        evidenceById={new Map()}
        onSelectEvidence={vi.fn()}
        onSaveSuggestion={onSaveSuggestion}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Save question for visit preparation" }));

    expect(onSaveSuggestion).toHaveBeenCalledWith(suggestion());
  });

  it("shows a refresh action for a saved question whose source is stale", () => {
    render(
      <QuestionSuggestionList
        report={report()}
        evidenceById={new Map()}
        onSelectEvidence={vi.fn()}
        onSaveSuggestion={vi.fn()}
        staleSuggestionIds={new Set(["suggestion-1"])}
      />,
    );

    expect(screen.getByRole("button", { name: "Refresh saved source" })).toBeInTheDocument();
  });
});
