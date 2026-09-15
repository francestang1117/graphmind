import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import QuestionSuggestionList from "../components/upload/medical/QuestionSuggestionList";
import type {
  MedicalInsightEvidence,
  MedicalInsightReport,
  MedicalQuestionSuggestion,
} from "../services/api";

function evidence(
  evidenceId: string,
  pageStart: number,
  sectionTitle: string,
): MedicalInsightEvidence {
  return {
    id: `row-${evidenceId}`,
    evidence_id: evidenceId,
    finding_id: "finding-1",
    chunk_id: `chunk-${evidenceId}`,
    section_id: "section-1",
    section_type: "results",
    section_title: sectionTitle,
    page_start: pageStart,
    page_end: pageStart,
    quote: `Source passage for ${evidenceId}`,
  };
}

function suggestion(
  overrides: Partial<MedicalQuestionSuggestion> = {},
): MedicalQuestionSuggestion {
  return {
    id: "question-1",
    question: "Which people were included in this study?",
    rationale: "The study describes a population, so this is useful to discuss.",
    category: "applicability",
    evidence_ids: ["EVIDENCE_001"],
    interpretation_type: "inference",
    ...overrides,
  };
}

function report(
  overrides: Partial<MedicalInsightReport> = {},
): MedicalInsightReport {
  return {
    schema_version: "medical-insights-v3",
    document_kind: "research_paper",
    language: "en",
    overview: {
      title: "Example paper",
      summary: "The paper reports a result.",
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
    question_suggestions: [],
    questions_for_professional: [],
    coverage: undefined,
    warnings: [],
    ...overrides,
  };
}

function renderList(
  currentReport: MedicalInsightReport,
  evidenceById = new Map<string, MedicalInsightEvidence>([
    ["EVIDENCE_001", evidence("EVIDENCE_001", 3, "Results")],
    ["EVIDENCE_002", evidence("EVIDENCE_002", 5, "Limitations")],
  ]),
) {
  const onSelectEvidence = vi.fn();
  render(
    <QuestionSuggestionList
      report={currentReport}
      evidenceById={evidenceById}
      onSelectEvidence={onSelectEvidence}
    />,
  );
  return onSelectEvidence;
}

describe("QuestionSuggestionList", () => {
  beforeEach(() => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("renders a structured question with its category, rationale, and evidence location", async () => {
    const onSelectEvidence = renderList(report({ question_suggestions: [suggestion()] }));

    expect(screen.getByText("Applicability")).toBeInTheDocument();
    expect(screen.getByText("Which people were included in this study?")).toBeInTheDocument();
    expect(screen.getByText("The study describes a population, so this is useful to discuss.")).toBeInTheDocument();
    const evidenceButton = screen.getByRole("button", { name: /Page 3.*Results/i });

    await userEvent.setup().click(evidenceButton);

    expect(onSelectEvidence).toHaveBeenCalledWith(
      expect.objectContaining({ evidence_id: "EVIDENCE_001" }),
    );
  });

  it("renders and opens every known evidence reference", async () => {
    const onSelectEvidence = renderList(
      report({
        question_suggestions: [
          suggestion({ evidence_ids: ["EVIDENCE_001", "EVIDENCE_002"] }),
        ],
      }),
    );
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: /Page 3.*Results/i }));
    await user.click(screen.getByRole("button", { name: /Page 5.*Limitations/i }));

    expect(onSelectEvidence).toHaveBeenCalledTimes(2);
  });

  it("copies the question and rationale in a readable format", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    renderList(report({ question_suggestions: [suggestion()] }));

    fireEvent.click(screen.getByRole("button", { name: "Copy this question" }));

    expect(writeText).toHaveBeenCalledWith(
      "I would like to ask my healthcare professional:\n"
        + "Which people were included in this study?\n\n"
        + "Why I want to ask:\n"
        + "The study describes a population, so this is useful to discuss.",
    );
    expect(await screen.findByText("Copied")).toBeInTheDocument();
  });

  it("reports clipboard failures without hiding the question", async () => {
    const writeText = vi.fn().mockRejectedValue(new Error("blocked"));
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    renderList(report({ question_suggestions: [suggestion()] }));

    fireEvent.click(screen.getByRole("button", { name: "Copy this question" }));

    expect(await screen.findByText("Could not copy this question. Please select the text manually.")).toBeInTheDocument();
    expect(screen.getByText("Which people were included in this study?")).toBeInTheDocument();
  });

  it("prefers structured suggestions over legacy questions", () => {
    renderList(
      report({
        question_suggestions: [suggestion()],
        questions_for_professional: ["Legacy question should stay hidden."],
      }),
    );

    expect(screen.getByText("Which people were included in this study?")).toBeInTheDocument();
    expect(screen.queryByText("Legacy question should stay hidden.")).not.toBeInTheDocument();
  });

  it("falls back to legacy questions for older reports", () => {
    renderList(report({
      schema_version: "medical-insights-v2",
      questions_for_professional: ["What should I discuss with a professional?"],
    }));

    expect(screen.getByText("What should I discuss with a professional?")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Questions to discuss with a healthcare professional" })).toBeInTheDocument();
  });

  it("does not show legacy questions in a V3 report", () => {
    renderList(report({ questions_for_professional: ["Uncited legacy question."] }));

    expect(screen.queryByText("Uncited legacy question.")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Questions to discuss with a healthcare professional" })).not.toBeInTheDocument();
  });

  it("returns no section when both question formats are empty", () => {
    const { container } = render(
      <QuestionSuggestionList
        report={report()}
        evidenceById={new Map()}
        onSelectEvidence={vi.fn()}
      />,
    );

    expect(container.firstChild).toBeNull();
  });

  it("renders at most five structured suggestions", () => {
    const suggestions = Array.from({ length: 6 }, (_, index) =>
      suggestion({
        id: `question-${index + 1}`,
        question: `Which result should I discuss in question ${index + 1}?`,
      }),
    );
    renderList(report({ question_suggestions: suggestions }));

    expect(screen.getAllByRole("article")).toHaveLength(5);
    expect(screen.queryByText("Which result should I discuss in question 6?")).not.toBeInTheDocument();
  });

  it("uses a safe fallback label for an unknown category", () => {
    renderList(
      report({
        question_suggestions: [
          suggestion({ category: "future_category" as MedicalQuestionSuggestion["category"] }),
        ],
      }),
    );

    expect(screen.getByText("Discussion question")).toBeInTheDocument();
  });

  it("does not render unknown evidence ids as clickable locations", () => {
    renderList(
      report({
        question_suggestions: [suggestion({ evidence_ids: ["EVIDENCE_UNKNOWN"] })],
      }),
    );

    expect(screen.queryByRole("button", { name: /Page/ })).not.toBeInTheDocument();
    expect(screen.getByText("Which people were included in this study?")).toBeInTheDocument();
  });

  it("renders long question text without changing the card contract", () => {
    const longQuestion = `Which people were included in this study? ${"Please discuss the scope. ".repeat(18)}`;
    renderList(
      report({
        question_suggestions: [suggestion({ question: longQuestion })],
      }),
    );

    expect(screen.getByText(/Which people were included in this study\? Please discuss the scope\./)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy this question" })).toBeInTheDocument();
  });
});
