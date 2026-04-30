import { useQuery } from "@tanstack/react-query";
import { fetchGraph, type GraphData } from "../services/api";

const demoGraph: GraphData = {
  nodes: [
    { id: "ml", label: "Machine Learning", type: "CONCEPT", size: 13 },
    { id: "nn", label: "Neural Network", type: "CONCEPT", size: 12 },
    { id: "dl", label: "Deep Learning", type: "CONCEPT", size: 11 },
    { id: "tf", label: "TensorFlow", type: "FRAMEWORK", size: 9 },
    { id: "pt", label: "PyTorch", type: "FRAMEWORK", size: 9 },
    { id: "py", label: "Python", type: "LANGUAGE", size: 9 },
    { id: "bp", label: "Backpropagation", type: "CONCEPT", size: 8 },
    { id: "gd", label: "Gradient Descent", type: "CONCEPT", size: 8 },
    { id: "cnn", label: "Convolutional Net", type: "CONCEPT", size: 8 },
    { id: "doc1", label: "ml-intro.md", type: "DOCUMENT", size: 10 },
    { id: "doc2", label: "neural-nets.pdf", type: "DOCUMENT", size: 10 },
  ],
  edges: [
    { source: "ml", target: "nn", type: "RELATED_TO" },
    { source: "ml", target: "dl", type: "RELATED_TO" },
    { source: "dl", target: "nn", type: "RELATED_TO" },
    { source: "nn", target: "bp", type: "RELATED_TO" },
    { source: "bp", target: "gd", type: "RELATED_TO" },
    { source: "nn", target: "tf", type: "USES" },
    { source: "nn", target: "pt", type: "USES" },
    { source: "py", target: "tf", type: "USES" },
    { source: "py", target: "pt", type: "USES" },
    { source: "doc1", target: "ml", type: "MENTIONS" },
    { source: "doc2", target: "nn", type: "MENTIONS" },
    { source: "dl", target: "cnn", type: "RELATED_TO" },
  ],
  stats: {
    total_nodes: 11,
    total_edges: 12,
    node_types: {
      CONCEPT: 6,
      FRAMEWORK: 2,
      LANGUAGE: 1,
      DOCUMENT: 2,
    },
  },
};

export function useGraph() {
  // The graph tab should stay useful before the backend graph module exists.
  const graphQuery = useQuery({
    queryKey: ["graph"],
    queryFn: async () => {
      try {
        const graph = await fetchGraph();
        return graph.nodes.length ? graph : demoGraph;
      } catch {
        return demoGraph;
      }
    },
    staleTime: 30_000,
  });

  const graph = graphQuery.data ?? demoGraph;

  return {
    nodes: graph.nodes,
    edges: graph.edges,
    stats: graph.stats,
    loading: graphQuery.isLoading,
    refreshing: graphQuery.isFetching,
    refetch: graphQuery.refetch,
  };
}
