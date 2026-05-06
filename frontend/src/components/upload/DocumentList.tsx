import { FileCode2, FileText, Layers3 } from "lucide-react";
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
  activeParsedFilename: string;
  onFilterChange: (filter: StatusFilter) => void;
  onDelete: (filename: string) => void;
  onDismissUpload?: (id: string) => void;
  onOpenFile?: (filename: string) => void;
  onViewParsed?: (filename: string, label: string) => void;
}

const filters: Array<{ value: StatusFilter; label: string }> = [
  { value: "all", label: "All" },
  { value: "done", label: "Done" },
  { value: "processing", label: "Indexing" },
];

function EmptyDocuments() {
  return (
    <div className="document-empty document-empty-intro">
      <div className="empty-stack" aria-hidden="true">
        <div className="empty-card empty-card-md">
          <FileText size={18} />
          <span>Markdown</span>
        </div>
        <div className="empty-card empty-card-code">
          <FileCode2 size={18} />
          <span>Code</span>
        </div>
        <div className="empty-card empty-card-pdf">
          <Layers3 size={18} />
          <span>PDF</span>
        </div>
      </div>
      <div className="empty-copy">
        <strong>Your workspace is ready</strong>
        <p>Drop in a document to validate, store, and prepare it for parsing.</p>
        <div className="empty-chips" aria-label="Supported file types">
          <span>.md</span>
          <span>.pdf</span>
          <span>.txt</span>
          <span>.docx</span>
          <span>.py</span>
          <span>.js</span>
          <span>.ts</span>
          <span>.json</span>
          <span>.csv</span>
          <span>.html</span>
        </div>
      </div>
    </div>
  );
}

function EmptyFilter() {
  return (
    <div className="document-empty document-empty-filter">
      <strong>No files in this view</strong>
      <p>Switch filters or upload another document.</p>
    </div>
  );
}

function isRenderableUpload(upload: UploadState) {
  return Boolean(upload.filename) && Number.isFinite(upload.file_size);
}

export default function DocumentList({
  files,
  uploads,
  filter,
  demo,
  deleting,
  activeParsedFilename,
  onFilterChange,
  onDelete,
  onDismissUpload,
  onOpenFile,
  onViewParsed,
}: Props) {
  // Keep active uploads above the saved list.
  const filteredFiles = files.filter((file) => {
    if (filter === "all") return true;
    return (file.status ?? "done") === filter;
  });
  const visibleUploads = uploads.filter(isRenderableUpload);
  const filteredUploads = visibleUploads.filter((upload) => {
    if (filter === "all") return true;
    return filter === "processing" && upload.status === "uploading";
  });
  const isEmpty = visibleUploads.length === 0 && files.length === 0;
  const hasNoFilteredFiles =
    files.length + visibleUploads.length > 0 &&
    filteredFiles.length === 0 &&
    filteredUploads.length === 0;

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
        {isEmpty && <EmptyDocuments />}
        {hasNoFilteredFiles && <EmptyFilter />}
        {filteredUploads.map((upload) => (
          <UploadRow upload={upload} key={upload.id} onDismiss={onDismissUpload} />
        ))}
        {filteredFiles.map((file) => (
          <DocumentRow
            file={file}
            key={file.filename}
            demo={demo}
            deleting={deleting === file.filename}
            parsedActive={activeParsedFilename === file.filename}
            onDelete={onDelete}
            onOpenFile={onOpenFile}
            onViewParsed={onViewParsed}
          />
        ))}
      </div>
    </section>
  );
}
