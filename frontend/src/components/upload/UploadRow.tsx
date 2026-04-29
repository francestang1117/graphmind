import { AlertCircle, CheckCircle2, Loader2, Trash2 } from "lucide-react";
import type { UploadState } from "../../hooks/useUpload";
import { formatSize } from "../../utils/fileMeta";
import FileIcon from "./FileIcon";

function uploadStatusLabel(upload: UploadState) {
  // The label mirrors the backend pipeline names without exposing internals.
  if (upload.status === "error") {
    if (upload.errorKind === "unsupported") return "Unsupported";
    if (upload.errorKind === "duplicate") return "Duplicate";
    return "Failed";
  }
  if (upload.status === "done") return "Done";
  if (upload.progress >= 80 || upload.step === "Indexing") return "Indexing";
  return `${upload.progress}%`;
}

// Implemented: temporary upload row with progress, pipeline step label, error state, and dismiss action.
export default function UploadRow({
  upload,
  onDismiss,
}: {
  upload: UploadState;
  onDismiss?: (id: string) => void;
}) {
  const statusClass =
    upload.status === "error"
      ? "error"
      : upload.status === "uploading"
        ? "processing"
        : "done";

  return (
    <div className={`document-row upload-row ${upload.status === "error" ? "error-row" : ""}`}>
      <FileIcon ext={upload.file_extension} />
      <div className="document-main">
        <strong>{upload.filename}</strong>
        <span>
          {formatSize(upload.file_size)} · {upload.step}
        </span>
        {upload.status === "uploading" && (
          <div className="row-progress">
            <div style={{ width: `${upload.progress}%` }} />
          </div>
        )}
        {upload.error && <small className="row-error">{upload.error}</small>}
      </div>
      <span className={`status-pill ${statusClass}`}>
        {upload.status === "uploading" && <Loader2 className="spin" size={13} />}
        {upload.status === "done" && <CheckCircle2 size={13} />}
        {upload.status === "error" && <AlertCircle size={13} />}
        {uploadStatusLabel(upload)}
      </span>
      {upload.status === "error" && onDismiss && (
        <button
          className="row-action"
          aria-label={`Dismiss ${upload.filename}`}
          onClick={() => onDismiss(upload.id)}
          type="button"
        >
          <Trash2 size={17} />
        </button>
      )}
    </div>
  );
}
