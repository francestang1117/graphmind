import { useQuery } from "@tanstack/react-query";
import { getDiseaseGuide, searchDiseaseGuides } from "../services/api";

export function useDiseaseGuideSearch(query: string) {
  const normalizedQuery = query.trim();
  return useQuery({
    queryKey: ["disease-guide-search", normalizedQuery],
    queryFn: () => searchDiseaseGuides(normalizedQuery, 20),
    enabled: normalizedQuery.length >= 2,
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
  });
}

export function useDiseaseGuide(
  conceptId: string | null,
  language = "zh-CN",
  region = "JP",
) {
  return useQuery({
    queryKey: ["disease-guide", conceptId ?? "none", language, region],
    queryFn: () => getDiseaseGuide(conceptId as string, language, region),
    enabled: Boolean(conceptId),
    staleTime: 10 * 60_000,
    refetchOnWindowFocus: false,
  });
}
