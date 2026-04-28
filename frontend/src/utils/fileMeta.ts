import { Code2, File, FileText } from "lucide-react";
import type { FileInfo } from "../stores/appStore";

// File visuals are centralized so upload rows and saved rows stay in sync.
export const fileTypeMeta: Record<string, { icon: typeof File; tone: string }> = {
  ".pdf": { icon: FileText, tone: "red" },
  ".md": { icon: FileText, tone: "blue" },
  ".txt": { icon: FileText, tone: "gray" },
  ".docx": { icon: FileText, tone: "blue" },
  ".py": { icon: Code2, tone: "green" },
  ".js": { icon: Code2, tone: "amber" },
  ".ts": { icon: Code2, tone: "violet" },
};

export const demoFiles: Array<FileInfo & { progress?: number }> = [
  {
    filename: "neural-networks.pdf",
    original_filename: "neural-networks.pdf",
    file_size: 2_300_000,
    file_extension: ".pdf",
    created_at: new Date(Date.now() - 3 * 86_400_000).toISOString(),
    status: "done",
  },
  {
    filename: "machine-learning-intro.md",
    original_filename: "machine-learning-intro.md",
    file_size: 14_900,
    file_extension: ".md",
    created_at: new Date(Date.now() - 2 * 86_400_000).toISOString(),
    status: "done",
  },
  {
    filename: "data-analysis.py",
    original_filename: "data-analysis.py",
    file_size: 8_200,
    file_extension: ".py",
    created_at: new Date(Date.now() - 86_400_000).toISOString(),
    status: "done",
  },
  {
    filename: "api-design-guide.md",
    original_filename: "api-design-guide.md",
    file_size: 22_100,
    file_extension: ".md",
    created_at: new Date().toISOString(),
    status: "processing",
    progress: 68,
  },
];

export function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function formatDate(iso: string) {
  const diffHours = (Date.now() - new Date(iso).getTime()) / 3_600_000;
  if (diffHours < 1) return "just now";
  if (diffHours < 24) return `${Math.floor(diffHours)}h ago`;
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
