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
  errorKind?: "unsupported" | "duplicate" | "failed";
}

const steps = ["Uploading", "Validating", "Saving", "Parsing", "Indexing", "Done"];
const allowedExtensions = new Set([
  ".md", ".pdf", ".txt", ".docx", ".py", ".js", ".ts", ".json", ".csv", ".html", ".htm",
]);
const supportedLabel = ".md, .pdf, .txt, .docx, .py, .js, .ts, .json, .csv, .html";

function fileExtension(filename: string) {
  const ext = filename.includes(".") ? `.${filename.split(".").pop()?.toLowerCase() ?? ""}` : "";
  return ext;
}

function isUsableFile(file: unknown): file is File {
  return file instanceof File && Boolean(file.name) && Number.isFinite(file.size);
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
    const message = typeof detail?.message === "string" ? detail.message : "";
    // The backend uses a 409 when SHA-256 content already exists, even if
    // the duplicate was uploaded with a different filename.
    if (error.response?.status === 409 || message.includes("already been uploaded")) {
      return {
        kind: "duplicate" as const,
        message: "This file is already in your documents.",
      };
    }
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

export function useUpload() {
  // Upload progress is temporary; saved files come back from the API list.
  const [uploads, setUploads] = useState<Record<string, UploadState>>({});
  const setFiles = useAppStore((state) => state.setFiles);

  const update = (id: string, patch: Partial<UploadState>) => {
    setUploads((prev) => ({ ...prev, [id]: { ...prev[id], ...patch } }));
  };

  const uploadFile = async (file: File) => {
    if (!isUsableFile(file)) {
      return;
    }

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
      const friendly = friendlyUploadError(error, ext);
      if (friendly.kind === "duplicate") {
        update(id, {
          status: "error",
          error: friendly.message,
          errorKind: friendly.kind,
          step: "Duplicate",
        });
        return;
      }

      const refreshed = await listDocuments().catch(() => []);
      const saved = refreshed.find(
        (doc) => doc.original_filename === file.name && doc.file_size === file.size,
      );

      // Sometimes the list has the saved row even if the request reported late.
      if (saved) {
        removeUpload(setUploads, id);
        setFiles(refreshed);
        return;
      }

      if (!file.name || !Number.isFinite(file.size)) {
        removeUpload(setUploads, id);
        setFiles(refreshed);
        return;
      }
      update(id, {
        status: "error",
        error: friendly.message,
        errorKind: friendly.kind,
        step: friendly.kind === "unsupported" ? "Not supported" : "Failed",
      });
    }
  };

  const uploadMany = (files: FileList | File[]) =>
    Promise.all(Array.from(files).filter(isUsableFile).map((file) => uploadFile(file)));

  const dismissUpload = (id: string) => removeUpload(setUploads, id);

  return { uploads: Object.values(uploads), uploadFile, uploadMany, dismissUpload };
}
