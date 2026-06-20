import { useQuery } from "@tanstack/react-query";
import { fetchGraph, type GraphData } from "../services/api";

const emptyGraph: GraphData = {
  nodes: [],
  edges: [],
  stats: {
    total_nodes: 0,
    total_edges: 0,
    node_types: {},
  },
};

export function useGraph() {
  const graphQuery = useQuery({
    queryKey: ["graph"],
    queryFn: fetchGraph,
    staleTime: 30_000,
  });

  const graph = graphQuery.data ?? emptyGraph;

  return {
    nodes: graph.nodes,
    edges: graph.edges,
    stats: graph.stats,
    loading: graphQuery.isLoading,
    refreshing: graphQuery.isFetching,
    error: graphQuery.isError,
    refetch: graphQuery.refetch,
  };
}
