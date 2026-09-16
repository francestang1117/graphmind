import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import VisitPreparationPanel from "../components/VisitPreparationPanel";
import type { ClinicianQuestion, VisitBrief } from "../services/api";

const questionHooks = vi.hoisted(() => ({ useClinicianQuestions: vi.fn() }));
const briefHooks = vi.hoisted(() => ({ useVisitBriefs: vi.fn() }));

vi.mock("../hooks/useClinicianQuestions", () => questionHooks);
vi.mock("../hooks/useVisitBriefs", () => briefHooks);

function question(overrides: Partial<ClinicianQuestion> = {}): ClinicianQuestion {
  return {
    id: "question-1",
    workspace_id: "workspace-1",
    document_id: "document-1",
    document_title: "example-paper.pdf",
    analysis_run_id: "run-1",
    suggestion_id: "suggestion-1",
    question: "Which people were included in this study?",
    rationale: "The population determines how the result can be interpreted.",
    category: "applicability",
    topic: "study_population",
    source_kind: "study_methods",
    source_id: "population",
    evidence_ids: ["EVIDENCE_001"],
    language: "en",
    status: "saved",
    priority: 2,
    position: 0,
    user_note: "Ask at the next appointment",
    version: 1,
    source_status: "current",
    created_at: "2026-09-16T00:00:00+00:00",
    updated_at: "2026-09-16T00:00:00+00:00",
    evidence: [{
      evidence_id: "EVIDENCE_001",
      chunk_id: "chunk-1",
      section_id: "section-1",
      section_type: "methods",
      section_title: "Methods",
      page_start: 2,
      page_end: 2,
      quote: "Adults with the condition were included.",
    }],
    ...overrides,
  };
}

function brief(): VisitBrief {
  return {
    id: "brief-1",
    workspace_id: "workspace-1",
    status: "active",
    language: "en",
    generated_at: "2026-09-16T00:00:00+00:00",
    data_cutoff_at: "2026-09-16T00:00:00+00:00",
    disclaimer: "This visit preparation sheet is for discussion with a healthcare professional.",
    items: [{
      id: "item-1",
      clinician_question_id: "question-1",
      document_id: "document-1",
      analysis_run_id: "run-1",
      position: 0,
      question: "Which people were included in this study?",
      rationale: "The population determines how the result can be interpreted.",
      user_note: "",
      evidence: [{
        evidence_id: "EVIDENCE_001",
        section_type: "methods",
        section_title: "Methods",
        page_start: 2,
        page_end: 2,
        quote: "Adults with the condition were included.",
      }],
    }],
  };
}

function configure(items: ClinicianQuestion[] = [question()]) {
  const updateQuestion = vi.fn().mockResolvedValue(items[0]);
  const deleteQuestion = vi.fn().mockResolvedValue(undefined);
  const createBrief = vi.fn().mockResolvedValue(brief());
  questionHooks.useClinicianQuestions.mockReturnValue({
    items,
    total: items.length,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
    updateQuestion,
    deleteQuestion,
    savedSuggestionIds: new Set(["suggestion-1"]),
    staleSuggestionIds: new Set(),
    saveQuestion: vi.fn(),
    savingSuggestionId: null,
    saveError: null,
  });
  briefHooks.useVisitBriefs.mockReturnValue({
    briefs: [],
    total: 0,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
    createBrief,
    creating: false,
    deleteBrief: vi.fn(),
    deleting: false,
  });
  return { updateQuestion, createBrief };
}

describe("VisitPreparationPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => cleanup());

  it("updates status and private notes with the current optimistic-lock version", async () => {
    const user = userEvent.setup();
    const { updateQuestion } = configure();
    render(<VisitPreparationPanel workspaceId="workspace-1" />);

    await user.selectOptions(screen.getByLabelText("Status"), "asked");
    const note = screen.getByLabelText("Private note");
    await user.clear(note);
    await user.type(note, "Bring this up with the specialist");
    fireEvent.blur(note);

    expect(updateQuestion).toHaveBeenCalledWith(expect.objectContaining({
      questionId: "question-1",
      status: "asked",
      expected_version: 1,
    }));
    expect(updateQuestion).toHaveBeenCalledWith(expect.objectContaining({
      questionId: "question-1",
      user_note: "Bring this up with the specialist",
      expected_version: 1,
    }));
  });

  it("does not allow an outdated source into the selection", () => {
    configure([question({ source_status: "outdated" })]);
    render(<VisitPreparationPanel workspaceId="workspace-1" />);

    expect(screen.getByText("Source needs refresh")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /Select question/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Create visit brief" })).toBeDisabled();
  });

  it("creates and shows a snapshot containing only the selected question", async () => {
    const user = userEvent.setup();
    const { createBrief } = configure();
    render(<VisitPreparationPanel workspaceId="workspace-1" />);

    await user.click(screen.getByRole("checkbox", { name: /Select question/ }));
    await user.click(screen.getByRole("button", { name: "Create visit brief" }));

    expect(createBrief).toHaveBeenCalledWith({ questionIds: ["question-1"], includeUserNotes: false });
    expect(await screen.findByText("Visit preparation / 就诊准备")).toBeInTheDocument();
    expect(screen.getByText("This visit preparation sheet is for discussion with a healthcare professional.")).toBeInTheDocument();
  });

  it("does not include private notes until the user opts in", async () => {
    const user = userEvent.setup();
    const { createBrief } = configure();
    render(<VisitPreparationPanel workspaceId="workspace-1" />);

    await user.click(screen.getByRole("checkbox", { name: /Select question/ }));
    await user.click(screen.getByRole("button", { name: "Create visit brief" }));

    expect(createBrief).toHaveBeenCalledWith({ questionIds: ["question-1"], includeUserNotes: false });
  });
});
