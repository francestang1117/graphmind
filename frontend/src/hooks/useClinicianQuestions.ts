import { useMemo, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  deleteClinicianQuestion,
  listClinicianQuestions,
  reorderClinicianQuestions,
  saveClinicianQuestion,
  updateClinicianQuestion,
  type ClinicianQuestionStatus,
  type ClinicianQuestion,
  type ClinicianQuestionList,
} from "../services/api";

export function useClinicianQuestions(
  workspaceId: string | null | undefined,
  documentId?: string | null,
) {
  const queryClient = useQueryClient();
  const queryKey = ["clinician-questions", workspaceId ?? "none"];
  const updateQueues = useRef(new Map<string, Promise<ClinicianQuestion>>());
  const latestVersions = useRef(new Map<string, number>());

  const query = useQuery({
    queryKey,
    queryFn: () => listClinicianQuestions(workspaceId as string, { includeDismissed: true }),
    enabled: Boolean(workspaceId),
    refetchOnWindowFocus: false,
  });

  const replaceQuestionCache = (updated: ClinicianQuestion | ClinicianQuestion[]) => {
    const updates = new Map(
      (Array.isArray(updated) ? updated : [updated]).map((item) => [item.id, item]),
    );
    queryClient.setQueryData<ClinicianQuestionList>(queryKey, (current) => {
      if (!current) return current;
      return {
        ...current,
        items: current.items.map((item) => updates.get(item.id) ?? item),
      };
    });
  };

  const saveMutation = useMutation({
    mutationFn: (input: { analysisRunId: string; suggestionId: string }) =>
      saveClinicianQuestion(workspaceId as string, {
        analysis_run_id: input.analysisRunId,
        suggestion_id: input.suggestionId,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey });
    },
  });

  const updateMutation = useMutation({
    mutationFn: (input: {
      questionId: string;
      status?: ClinicianQuestionStatus;
      priority?: 1 | 2 | 3;
      user_note?: string;
      expected_version: number;
    }) => {
      const { questionId, ...body } = input;
      return updateClinicianQuestion(workspaceId as string, questionId, body);
    },
    onSuccess: (updated) => {
      replaceQuestionCache(updated);
      void queryClient.invalidateQueries({ queryKey });
    },
  });

  type QuestionUpdateInput = {
    questionId: string;
    status?: ClinicianQuestionStatus;
    priority?: 1 | 2 | 3;
    user_note?: string;
    expected_version: number;
  };

  const updateQuestion = (input: QuestionUpdateInput) => {
    const previous = updateQueues.current.get(input.questionId);
    const run: Promise<ClinicianQuestion> = (previous ?? Promise.resolve()).then(async () => {
      // A queued edit must use the version returned by the preceding edit,
      // even when both UI events captured the same rendered question object.
      const expectedVersion = latestVersions.current.get(input.questionId)
        ?? input.expected_version;
      const updated = await updateMutation.mutateAsync({
        ...input,
        expected_version: expectedVersion,
      });
      latestVersions.current.set(input.questionId, updated.version);
      return updated;
    });

    const cleanup = () => {
      if (updateQueues.current.get(input.questionId) === run) {
        updateQueues.current.delete(input.questionId);
      }
    };
    // The caller awaits `run`; this side chain only cleans up queue state and
    // handles both outcomes so a failed update is not left unhandled.
    void run.then(cleanup, cleanup);
    updateQueues.current.set(input.questionId, run);
    return run;
  };

  const deleteMutation = useMutation({
    mutationFn: (questionId: string) =>
      deleteClinicianQuestion(workspaceId as string, questionId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey });
    },
  });

  const reorderMutation = useMutation({
    mutationFn: (input: {
      questionId: string;
      targetQuestionId: string;
      expectedVersion: number;
      targetExpectedVersion: number;
    }) => reorderClinicianQuestions(workspaceId as string, {
      question_id: input.questionId,
      target_question_id: input.targetQuestionId,
      expected_version: input.expectedVersion,
      target_expected_version: input.targetExpectedVersion,
    }),
    onSuccess: (updated) => {
      replaceQuestionCache(updated);
      void queryClient.invalidateQueries({ queryKey });
    },
  });

  const items = useMemo(() => query.data?.items ?? [], [query.data?.items]);
  const scopedItems = useMemo(
    () => documentId ? items.filter((item) => item.document_id === documentId) : items,
    [documentId, items],
  );
  const savedSuggestionIds = useMemo(
    () => new Set(
      scopedItems
        .filter((item: ClinicianQuestion) => item.source_status === "current")
        .map((item: ClinicianQuestion) => item.suggestion_id),
    ),
    [scopedItems],
  );
  const staleSuggestionIds = useMemo(
    () => new Set(
      scopedItems
        .filter((item: ClinicianQuestion) => item.source_status !== "current")
        .map((item: ClinicianQuestion) => item.suggestion_id),
    ),
    [scopedItems],
  );

  return {
    ...query,
    items: scopedItems,
    total: query.data?.total ?? 0,
    savedSuggestionIds,
    staleSuggestionIds,
    saveQuestion: saveMutation.mutateAsync,
    saving: saveMutation.isPending,
    savingSuggestionId: saveMutation.variables?.suggestionId ?? null,
    saveError: saveMutation.error,
    updateQuestion,
    reorderQuestions: reorderMutation.mutateAsync,
    updating: updateMutation.isPending || reorderMutation.isPending,
    updateError: updateMutation.error,
    deleteQuestion: deleteMutation.mutateAsync,
    deleting: deleteMutation.isPending,
    deleteError: deleteMutation.error,
  };
}
