import { Braces, Code2, File, FileText, Pilcrow } from "lucide-react";
import type { FileInfo } from "../stores/appStore";

// File visuals stay centralized so upload rows, saved rows, and future viewers agree.
export const fileTypeMeta: Record<string, { icon: typeof File; tone: string }> = {
  ".pdf": { icon: FileText, tone: "red" },
  ".md": { icon: Pilcrow, tone: "blue" },
  ".txt": { icon: FileText, tone: "gray" },
  ".docx": { icon: FileText, tone: "cyan" },
  ".py": { icon: Code2, tone: "green" },
  ".js": { icon: Braces, tone: "amber" },
  ".ts": { icon: Braces, tone: "violet" },
};

export function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function formatDate(iso: string) {
  // Keep new uploads feeling live without leaving everything stuck at "just now".
  const timestamp = new Date(iso).getTime();
  if (Number.isNaN(timestamp)) return "unknown";

  const diffSeconds = Math.max(0, Math.floor((Date.now() - timestamp) / 1000));
  if (diffSeconds < 45) return "just now";

  const diffMinutes = Math.floor(diffSeconds / 60);
  if (diffMinutes < 60) return `${diffMinutes}m ago`;

  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours}h ago`;

  const days = Math.floor(diffHours / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

export function displayName(file: FileInfo) {
  return file.original_filename || file.filename;
}

export function fileStatusLabel(status: FileInfo["status"]) {
  if (status === "processing") return "Indexing";
  if (status === "error") return "Error";
  return "Done";
}
