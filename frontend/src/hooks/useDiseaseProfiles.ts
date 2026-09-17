import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createDiseaseLink,
  deleteDiseaseLink,
  getDiseaseProfile,
  getDiseaseProfileItems,
  listDiseaseProfiles,
  listUnassignedDiseaseDocuments,
  searchDiseaseConcepts,
  type DiseaseProfileSection,
} from "../services/api";

export function useDiseaseProfiles(
  workspaceId: string | null | undefined,
  conceptId: string | null | undefined,
) {
  const queryClient = useQueryClient();
  const workspaceKey = workspaceId ?? "none";
  const listKey = ["disease-profiles", workspaceKey];
  const unassignedKey = ["disease-profile-unassigned", workspaceKey];

  const listQuery = useQuery({
    queryKey: listKey,
    queryFn: () => listDiseaseProfiles(workspaceId as string, { limit: 50 }),
    enabled: Boolean(workspaceId),
    refetchOnWindowFocus: false,
  });
  const selectedConceptId = conceptId ?? listQuery.data?.items[0]?.concept_id ?? null;
  const detailKey = ["disease-profile", workspaceKey, selectedConceptId ?? "none"];
  const detailQuery = useQuery({
    queryKey: detailKey,
    queryFn: () => getDiseaseProfile(selectedConceptId as string, workspaceId as string),
    enabled: Boolean(workspaceId && selectedConceptId),
    refetchOnWindowFocus: false,
  });
  const unassignedQuery = useQuery({
    queryKey: unassignedKey,
    queryFn: () => listUnassignedDiseaseDocuments(workspaceId as string),
    enabled: Boolean(workspaceId),
    refetchOnWindowFocus: false,
  });

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: listKey });
    void queryClient.invalidateQueries({ queryKey: detailKey });
    void queryClient.invalidateQueries({ queryKey: unassignedKey });
  };

  const linkMutation = useMutation({
    mutationFn: (input: {
      documentId: string;
      conceptId: string;
      matchedAlias: string;
    }) => createDiseaseLink(input.documentId, workspaceId as string, {
      concept_id: input.conceptId,
      matched_alias: input.matchedAlias,
    }),
    onSuccess: invalidate,
  });
  const unlinkMutation = useMutation({
    mutationFn: (input: { documentId: string; conceptId: string }) =>
      deleteDiseaseLink(input.documentId, input.conceptId, workspaceId as string),
    onSuccess: invalidate,
  });

  return {
    list: listQuery.data?.items ?? [],
    selectedConceptId,
    listQuery,
    detail: detailQuery.data ?? null,
    detailQuery,
    unassigned: unassignedQuery.data?.items ?? [],
    unassignedQuery,
    linkDocument: linkMutation.mutateAsync,
    linking: linkMutation.isPending,
    linkError: linkMutation.error,
    unlinkDocument: unlinkMutation.mutateAsync,
    unlinking: unlinkMutation.isPending,
    unlinkError: unlinkMutation.error,
  };
}

export function useDiseaseConceptSearch(
  query: string,
  enabled = true,
) {
  return useQuery({
    queryKey: ["disease-concept-search", query.trim()],
    queryFn: () => searchDiseaseConcepts(query.trim(), 20),
    enabled: enabled && query.trim().length >= 2,
    staleTime: 60_000,
  });
}

export function useDiseaseProfileItems(
  workspaceId: string | null | undefined,
  conceptId: string | null | undefined,
  section: DiseaseProfileSection,
  cursor?: string | null,
  enabled = true,
) {
  return useQuery({
    queryKey: ["disease-profile-items", workspaceId ?? "none", conceptId ?? "none", section, cursor ?? "start"],
    queryFn: () => getDiseaseProfileItems(
      conceptId as string,
      section,
      workspaceId as string,
      { limit: 20, cursor },
    ),
    enabled: enabled && Boolean(workspaceId && conceptId),
    refetchOnWindowFocus: false,
  });
}
