import { useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  deleteClinicianQuestion,
  listClinicianQuestions,
  saveClinicianQuestion,
  updateClinicianQuestion,
  type ClinicianQuestionStatus,
  type ClinicianQuestion,
} from "../services/api";

export function useClinicianQuestions(
  workspaceId: string | null | undefined,
  documentId?: string | null,
) {
  const queryClient = useQueryClient();
  const queryKey = ["clinician-questions", workspaceId ?? "none"];

  const query = useQuery({
    queryKey,
    queryFn: () => listClinicianQuestions(workspaceId as string, { includeDismissed: true }),
    enabled: Boolean(workspaceId),
    refetchOnWindowFocus: false,
  });

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
      position?: number;
      user_note?: string;
      expected_version: number;
    }) => {
      const { questionId, ...body } = input;
      return updateClinicianQuestion(workspaceId as string, questionId, body);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (questionId: string) =>
      deleteClinicianQuestion(workspaceId as string, questionId),
    onSuccess: () => {
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
    updateQuestion: updateMutation.mutateAsync,
    updating: updateMutation.isPending,
    updateError: updateMutation.error,
    deleteQuestion: deleteMutation.mutateAsync,
    deleting: deleteMutation.isPending,
    deleteError: deleteMutation.error,
  };
}
