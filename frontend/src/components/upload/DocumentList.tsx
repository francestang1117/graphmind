import type { FileInfo } from "../../stores/appStore";
import type { UploadState } from "../../hooks/useUpload";
import DocumentRow from "./DocumentRow";
import UploadRow from "./UploadRow";

export type StatusFilter = "all" | "done" | "processing";

interface Props {
  files: Array<FileInfo & { progress?: number }>;
  uploads: UploadState[];
  filter: StatusFilter;
  demo: boolean;
  deleting: string | null;
  onFilterChange: (filter: StatusFilter) => void;
  onDelete: (filename: string) => void;
  onViewParsed?: (filename: string) => void;
}

const filters: Array<{ value: StatusFilter; label: string }> = [
  { value: "all", label: "All" },
  { value: "done", label: "Done" },
  { value: "processing", label: "Indexing" },
];

// Implemented: saved-file rows, in-flight upload rows, status filtering, delete, and Markdown viewer entry.
export default function DocumentList({
  files,
  uploads,
  filter,
  demo,
  deleting,
  onFilterChange,
  onDelete,
  onViewParsed,
}: Props) {
  // Upload rows stay above saved rows so active work is always visible.
  const filteredFiles = files.filter((file) => {
    if (filter === "all") return true;
    return (file.status ?? "done") === filter;
  });

  return (
    <section className="document-list-section">
      <div className="document-list-header">
        <div className="section-heading">All documents</div>
        <div className="status-filters" aria-label="Document status filters">
          {filters.map((item) => (
            <button
              key={item.value}
              className={filter === item.value ? "active" : ""}
              onClick={() => onFilterChange(item.value)}
              type="button"
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      <div className="document-list">
        {uploads.map((upload) => (
          <UploadRow upload={upload} key={upload.id} />
        ))}
        {filteredFiles.map((file) => (
          <DocumentRow
            file={file}
            key={file.filename}
            demo={demo}
            deleting={deleting === file.filename}
            onDelete={onDelete}
            onViewParsed={onViewParsed}
          />
        ))}
      </div>
    </section>
  );
}
