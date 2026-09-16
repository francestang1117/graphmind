import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useClinicianQuestions } from "../hooks/useClinicianQuestions";
import type { ClinicianQuestion } from "../services/api";

const api = vi.hoisted(() => ({
  listClinicianQuestions: vi.fn(),
  reorderClinicianQuestions: vi.fn(),
  saveClinicianQuestion: vi.fn(),
  updateClinicianQuestion: vi.fn(),
  deleteClinicianQuestion: vi.fn(),
}));

vi.mock("../services/api", () => api);

function question(overrides: Partial<ClinicianQuestion> = {}): ClinicianQuestion {
  return {
    id: "question-1",
    workspace_id: "workspace-1",
    document_id: "document-1",
    document_title: "paper.pdf",
    analysis_run_id: "run-1",
    suggestion_id: "suggestion-1",
    question: "Which people were included in this study?",
    rationale: "The population is important to discuss.",
    category: "applicability",
    topic: "study_population",
    source_kind: "study_methods",
    source_id: "population",
    evidence_ids: ["EVIDENCE_001"],
    language: "en",
    status: "saved",
    priority: 2,
    position: 0,
    user_note: "",
    version: 1,
    source_status: "current",
    evidence: [],
    created_at: "2026-09-16T00:00:00+00:00",
    updated_at: "2026-09-16T00:00:00+00:00",
    ...overrides,
  };
}

function wrapper({ children }: PropsWithChildren) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useClinicianQuestions", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("serializes edits for one question and forwards the returned version", async () => {
    api.listClinicianQuestions.mockResolvedValue({ items: [question()], total: 1 });
    let releaseFirst!: (value: ClinicianQuestion) => void;
    const firstResponse = new Promise<ClinicianQuestion>((resolve) => {
      releaseFirst = resolve;
    });
    api.updateClinicianQuestion
      .mockImplementationOnce(() => firstResponse)
      .mockImplementationOnce((_workspaceId: string, _questionId: string, body: { expected_version: number }) =>
        Promise.resolve(question({ version: body.expected_version + 1, priority: 1 })));

    const { result } = renderHook(() => useClinicianQuestions("workspace-1"), { wrapper });
    let firstUpdate!: Promise<ClinicianQuestion>;
    let secondUpdate!: Promise<ClinicianQuestion>;
    act(() => {
      firstUpdate = result.current.updateQuestion({
        questionId: "question-1",
        user_note: "Ask about follow-up",
        expected_version: 1,
      });
      secondUpdate = result.current.updateQuestion({
        questionId: "question-1",
        priority: 1,
        expected_version: 1,
      });
    });

    await waitFor(() => expect(api.updateClinicianQuestion).toHaveBeenCalledTimes(1));
    expect(api.updateClinicianQuestion.mock.calls[0][2]).toMatchObject({
      user_note: "Ask about follow-up",
      expected_version: 1,
    });

    await act(async () => {
      releaseFirst(question({ version: 2, user_note: "Ask about follow-up" }));
      await Promise.all([firstUpdate, secondUpdate]);
    });

    expect(api.updateClinicianQuestion).toHaveBeenCalledTimes(2);
    expect(api.updateClinicianQuestion.mock.calls[1][2]).toMatchObject({
      priority: 1,
      expected_version: 2,
    });
  });
});
