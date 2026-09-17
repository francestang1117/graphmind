import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createVisitBrief,
  deleteVisitBrief,
  listVisitBriefs,
  type VisitBrief,
} from "../services/api";

export function useVisitBriefs(workspaceId: string | null | undefined) {
  const queryClient = useQueryClient();
  const queryKey = ["visit-briefs", workspaceId ?? "none"];

  const query = useQuery({
    queryKey,
    queryFn: () => listVisitBriefs(workspaceId as string),
    enabled: Boolean(workspaceId),
    refetchOnWindowFocus: false,
  });

  const createMutation = useMutation({
    mutationFn: (input: { questionIds: string[]; includeUserNotes: boolean }) =>
      createVisitBrief(workspaceId as string, {
        question_ids: input.questionIds,
        include_user_notes: input.includeUserNotes,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (briefId: string) => deleteVisitBrief(workspaceId as string, briefId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey });
    },
  });

  return {
    ...query,
    briefs: query.data?.items ?? [],
    total: query.data?.total ?? 0,
    createBrief: createMutation.mutateAsync,
    creating: createMutation.isPending,
    createdBrief: (createMutation.data as VisitBrief | undefined) ?? null,
    createError: createMutation.error,
    deleteBrief: deleteMutation.mutateAsync,
    deleting: deleteMutation.isPending,
    deleteError: deleteMutation.error,
  };
}
