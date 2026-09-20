import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createDiseaseLink,
  deleteDiseaseLink,
  getDiseaseProfile,
  getDiseaseProfileDocuments,
  getDiseaseProfileExternalSourceDocuments,
  getDiseaseProfileItems,
  listDiseaseProfiles,
  listUnassignedDiseaseDocuments,
  previewDiseaseProfileComparison,
  type ComparisonPreviewRequest,
  type DiseaseProfileItem,
  type DiseaseProfileDocumentsPage,
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

  const listQuery = useInfiniteQuery({
    queryKey: listKey,
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => listDiseaseProfiles(workspaceId as string, {
      limit: 50,
      cursor: pageParam,
    }),
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    enabled: Boolean(workspaceId),
    refetchOnWindowFocus: false,
  });
  const profiles = listQuery.data?.pages.flatMap((page) => page.items) ?? [];
  const selectedConceptId = conceptId ?? profiles[0]?.concept_id ?? null;
  const detailKey = ["disease-profile", workspaceKey, selectedConceptId ?? "none"];
  const detailQuery = useQuery({
    queryKey: detailKey,
    queryFn: () => getDiseaseProfile(selectedConceptId as string, workspaceId as string),
    enabled: Boolean(workspaceId && selectedConceptId),
    refetchOnWindowFocus: false,
  });
  const unassignedQuery = useInfiniteQuery({
    queryKey: unassignedKey,
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => listUnassignedDiseaseDocuments(workspaceId as string, {
      limit: 20,
      cursor: pageParam,
    }),
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    enabled: Boolean(workspaceId),
    refetchOnWindowFocus: false,
  });
  const initialDocumentPage: DiseaseProfileDocumentsPage | null = detailQuery.data
    ? {
        items: detailQuery.data.documents,
        next_cursor: detailQuery.data.documents_next_cursor ?? null,
      }
    : null;
  const detailDocumentKey = initialDocumentPage
    ? JSON.stringify(initialDocumentPage.items.map((item) => ({
        document_id: item.document_id,
        title: item.title,
        document_date: item.document_date,
        parsed_source_hash: item.parsed_source_hash,
        current_analysis_run_id: item.current_analysis_run_id,
        source_status: item.source_status,
      })))
    : "none";
  const linkedDocumentsQuery = useInfiniteQuery({
    queryKey: [...detailKey, "documents", detailDocumentKey, initialDocumentPage?.next_cursor ?? null],
    initialPageParam: "__detail__",
    queryFn: ({ pageParam }) => {
      if (pageParam === "__detail__") {
        return Promise.resolve(initialDocumentPage as DiseaseProfileDocumentsPage);
      }
      return getDiseaseProfileDocuments(
        selectedConceptId as string,
        workspaceId as string,
        { limit: 20, cursor: pageParam },
      );
    },
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    enabled: Boolean(workspaceId && selectedConceptId && initialDocumentPage),
    refetchOnWindowFocus: false,
  });

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: listKey });
    void queryClient.invalidateQueries({ queryKey: detailKey });
    void queryClient.invalidateQueries({ queryKey: unassignedKey });
    void queryClient.invalidateQueries({
      queryKey: ["disease-profile-items", workspaceKey],
    });
    void queryClient.invalidateQueries({
      queryKey: ["disease-profile-external-source-documents", workspaceKey],
    });
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
    list: profiles,
    hasMoreProfiles: Boolean(listQuery.hasNextPage),
    loadMoreProfiles: listQuery.fetchNextPage,
    loadingMoreProfiles: listQuery.isFetchingNextPage,
    selectedConceptId,
    listQuery,
    detail: detailQuery.data ?? null,
    detailQuery,
    unassigned: dedupeDocuments(
      unassignedQuery.data?.pages.flatMap((page) => page.items) ?? [],
    ),
    unassignedTotal: unassignedQuery.data?.pages[0]?.total ?? 0,
    unassignedQuery,
    hasMoreUnassigned: Boolean(unassignedQuery.hasNextPage),
    loadMoreUnassigned: unassignedQuery.fetchNextPage,
    loadingMoreUnassigned: unassignedQuery.isFetchingNextPage,
    linkedDocuments: dedupeDocuments(
      linkedDocumentsQuery.data?.pages.flatMap((page) => page.items) ?? [],
    ),
    documentsQuery: linkedDocumentsQuery,
    hasMoreDocuments: Boolean(linkedDocumentsQuery.hasNextPage),
    loadMoreDocuments: linkedDocumentsQuery.fetchNextPage,
    loadingMoreDocuments: linkedDocumentsQuery.isFetchingNextPage,
    linkDocument: linkMutation.mutateAsync,
    linking: linkMutation.isPending,
    linkError: linkMutation.error,
    unlinkDocument: unlinkMutation.mutateAsync,
    unlinking: unlinkMutation.isPending,
    unlinkError: unlinkMutation.error,
  };
}

function dedupeDocuments<T extends { document_id: string }>(items: T[]): T[] {
  return Array.from(new Map(items.map((item) => [item.document_id, item])).values());
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

export function useDiseaseProfileExternalSourceDocuments(
  workspaceId: string | null | undefined,
  conceptId: string | null | undefined,
  item: DiseaseProfileItem | null,
) {
  const source = item?.item_type === "article" ? item.source : "";
  const externalId = item?.item_type === "article" ? item.external_id : "";
  return useInfiniteQuery({
    queryKey: [
      "disease-profile-external-source-documents",
      workspaceId ?? "none",
      conceptId ?? "none",
      source,
      externalId,
    ],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => getDiseaseProfileExternalSourceDocuments(
      conceptId as string,
      workspaceId as string,
      source,
      externalId,
      { limit: 20, cursor: pageParam },
    ),
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    enabled: Boolean(workspaceId && conceptId && source && externalId),
    refetchOnWindowFocus: false,
  });
}

export function useDiseaseComparisonPreview(
  workspaceId: string | null | undefined,
  conceptId: string | null | undefined,
) {
  return useMutation({
    mutationFn: (input: ComparisonPreviewRequest) => previewDiseaseProfileComparison(
      conceptId as string,
      workspaceId as string,
      input,
    ),
  });
}
