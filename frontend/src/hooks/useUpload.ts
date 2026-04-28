import { useState } from "react";
import { listDocuments, uploadDocument } from "../services/api";
import { useAppStore } from "../stores/appStore";

export interface UploadState {
  id: string;
  filename: string;
  file_size: number;
  file_extension: string;
  progress: number;
  step: string;
  status: "uploading" | "done" | "error";
  error?: string;
}

const steps = ["Uploading", "Validating", "Saving", "Parsing", "Indexing", "Done"];

// Implemented: multi-file upload orchestration, progress mapping, refresh after upload, and error capture.
export function useUpload() {
  // Track upload rows separately from saved documents so progress can disappear cleanly.
  const [uploads, setUploads] = useState<Record<string, UploadState>>({});
  const setFiles = useAppStore((state) => state.setFiles);

  const update = (id: string, patch: Partial<UploadState>) => {
    setUploads((prev) => ({ ...prev, [id]: { ...prev[id], ...patch } }));
  };

  const uploadFile = async (file: File) => {
    const id = `${file.name}-${file.lastModified}-${Date.now()}`;
    setUploads((prev) => ({
      ...prev,
      [id]: {
        id,
        filename: file.name,
        file_size: file.size,
        file_extension: `.${file.name.split(".").pop()?.toLowerCase() ?? ""}`,
        progress: 0,
        step: steps[0],
        status: "uploading",
      },
    }));

    try {
      await uploadDocument(file, (pct) => {
        const step = steps[Math.min(Math.floor(pct / 20), steps.length - 1)];
        update(id, { progress: pct, step });
      });

      update(id, { progress: 100, step: "Done", status: "done" });
      setFiles(await listDocuments());

      window.setTimeout(() => {
        setUploads((prev) => {
          const next = { ...prev };
          delete next[id];
          return next;
        });
      }, 1500);
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Upload failed. Check backend logs.";
      update(id, { status: "error", error: message, step: "Failed" });
    }
  };

  const uploadMany = (files: FileList | File[]) =>
    Promise.all(Array.from(files).map((file) => uploadFile(file)));

  return { uploads: Object.values(uploads), uploadFile, uploadMany };
}
