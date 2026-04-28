import { create } from "zustand";

export interface FileInfo {
  filename: string;
  stored_filename?: string;
  original_filename?: string;
  file_size: number;
  file_extension: string;
  file_hash?: string;
  mime_type?: string;
  created_at: string;
  modified_at?: string;
  status?: "done" | "processing" | "error";
}

export interface GraphStats {
  total_nodes: number;
  total_edges: number;
  node_types?: Record<string, number>;
}

interface AppState {
  backendOnline: boolean;
  setBackendOnline: (v: boolean) => void;

  files: FileInfo[];
  setFiles: (files: FileInfo[]) => void;
  addFile: (file: FileInfo) => void;
  removeFile: (name: string) => void;

  graphStats: GraphStats | null;
  setGraphStats: (s: GraphStats | null) => void;

  conversationId: string | null;
  setConversationId: (id: string | null) => void;
}

// A tiny shared store is enough here; server data still comes through the API layer.
export const useAppStore = create<AppState>((set) => ({
  backendOnline: false,
  setBackendOnline: (backendOnline) => set({ backendOnline }),

  files: [],
  setFiles: (files) =>
    set({
      files: files.map((file) => ({ ...file, status: file.status ?? "done" })),
    }),
  addFile: (file) =>
    set((state) => ({
      files: [{ ...file, status: file.status ?? "done" }, ...state.files],
    })),
  removeFile: (name) =>
    set((state) => ({ files: state.files.filter((f) => f.filename !== name) })),

  graphStats: null,
  setGraphStats: (graphStats) => set({ graphStats }),

  conversationId: null,
  setConversationId: (conversationId) => set({ conversationId }),
}));
