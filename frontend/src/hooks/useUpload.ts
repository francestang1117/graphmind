import axios from "axios";
import type { Dispatch, SetStateAction } from "react";
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
  errorKind?: "unsupported" | "failed";
}

const steps = ["Uploading", "Validating", "Saving", "Parsing", "Indexing", "Done"];
const allowedExtensions = new Set([".md", ".pdf", ".txt", ".docx", ".py", ".js", ".ts"]);
const supportedLabel = ".md, .pdf, .txt, .docx, .py, .js, .ts";

function fileExtension(filename: string) {
  const ext = filename.includes(".") ? `.${filename.split(".").pop()?.toLowerCase() ?? ""}` : "";
  return ext;
}

function removeUpload(
  setUploads: Dispatch<SetStateAction<Record<string, UploadState>>>,
  id: string,
) {
  setUploads((prev) => {
    const next = { ...prev };
    delete next[id];
    return next;
  });
}

function friendlyUploadError(error: unknown, ext: string) {
  // Keep transport-level errors out of the UI; users need the next action, not status codes.
  if (!allowedExtensions.has(ext)) {
    return {
      kind: "unsupported" as const,
      message: `This file type is not supported. Use ${supportedLabel}.`,
    };
  }

  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    const text = typeof detail === "string" ? detail : "";
    if (text.includes("not permitted")) {
      return {
        kind: "unsupported" as const,
        message: `This file type is not supported. Use ${supportedLabel}.`,
      };
    }
    if (text.includes("empty")) {
      return { kind: "failed" as const, message: "This file is empty." };
    }
    if (text.includes("exceeds")) {
      return { kind: "failed" as const, message: "This file is larger than the upload limit." };
    }
    if (text.includes("dangerous")) {
      return { kind: "failed" as const, message: "This file was blocked by the safety check." };
    }
    if (text.includes("Detected type") || text.includes("signature")) {
      return { kind: "failed" as const, message: "The file contents do not match its extension." };
    }
  }

  return { kind: "failed" as const, message: "Upload failed. Please try again." };
}

// Implemented: multi-file upload orchestration, progress mapping, saved-row replacement, and friendly errors.
export function useUpload() {
  // Track upload rows separately from saved documents so progress can disappear cleanly.
  const [uploads, setUploads] = useState<Record<string, UploadState>>({});
  const setFiles = useAppStore((state) => state.setFiles);

  const update = (id: string, patch: Partial<UploadState>) => {
    setUploads((prev) => ({ ...prev, [id]: { ...prev[id], ...patch } }));
  };

  const uploadFile = async (file: File) => {
    const id = `${file.name}-${file.lastModified}-${Date.now()}`;
    const ext = fileExtension(file.name);

    if (!allowedExtensions.has(ext)) {
      return;
    }

    setUploads((prev) => ({
      ...prev,
      [id]: {
        id,
        filename: file.name,
        file_size: file.size,
        file_extension: ext,
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

      removeUpload(setUploads, id);
      setFiles(await listDocuments());
    } catch (error) {
      const refreshed = await listDocuments().catch(() => []);
      const saved = refreshed.find(
        (doc) => doc.original_filename === file.name && doc.file_size === file.size,
      );

      // If the request failed after storage completed, trust the backend list over the request error.
      if (saved) {
        removeUpload(setUploads, id);
        setFiles(refreshed);
        return;
      }

      const friendly = friendlyUploadError(error, ext);
      update(id, {
        status: "error",
        error: friendly.message,
        errorKind: friendly.kind,
        step: friendly.kind === "unsupported" ? "Not supported" : "Failed",
      });
    }
  };

  const uploadMany = (files: FileList | File[]) =>
    Promise.all(Array.from(files).map((file) => uploadFile(file)));

  return { uploads: Object.values(uploads), uploadFile, uploadMany };
}
