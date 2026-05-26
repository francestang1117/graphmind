import { AlertCircle, CheckCircle2, Loader2, RotateCcw, Trash2, XCircle } from "lucide-react";
import type { UploadState } from "../../hooks/useUpload";
import { formatSize } from "../../utils/fileMeta";
import FileIcon from "./FileIcon";

function uploadStatusLabel(upload: UploadState) {
  // The label mirrors the backend pipeline names without exposing internals.
  if (upload.status === "error") {
    if (upload.errorKind === "unsupported") return "Unsupported";
    if (upload.errorKind === "duplicate") return "Duplicate";
    if (upload.errorKind === "cancelled") return "Cancelled";
    return "Failed";
  }
  if (upload.status === "done") return "Done";
  if (upload.progress >= 80 || upload.step === "Indexing") return "Indexing";
  return `${upload.progress}%`;
}

function processingModeLabel(upload: UploadState) {
  // This is mostly for local dev: if there is no worker job, the row says so
  // instead of making the missing cancel button look broken.
  if (upload.processingMode === "worker") return "Worker job";
  if (upload.processingMode === "local") return "Local";
  return null;
}

export default function UploadRow({
  upload,
  onDismiss,
  onCancel,
  onRetry,
}: {
  upload: UploadState;
  onDismiss?: (id: string) => void;
  onCancel?: (id: string) => void;
  onRetry?: (id: string) => void;
}) {
  const statusClass =
    upload.status === "error"
      ? "error"
      : upload.status === "uploading"
        ? "processing"
        : "done";

  const modeLabel = processingModeLabel(upload);

  return (
    <div className={`document-row upload-row ${upload.status === "error" ? "error-row" : ""}`}>
      <FileIcon ext={upload.file_extension} />
      <div className="document-main">
        <strong>{upload.filename}</strong>
        <div className="row-meta">
          <span>{formatSize(upload.file_size)}</span>
          <span>{upload.step}</span>
          {modeLabel && <span className="processing-tag">{modeLabel}</span>}
        </div>
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
      <div className="row-actions">
        {upload.status === "uploading" && upload.jobId && onCancel && (
          <button
            className="row-action"
            aria-label={`Cancel ${upload.filename}`}
            onClick={() => onCancel(upload.id)}
            type="button"
          >
            <XCircle size={17} />
          </button>
        )}
        {upload.status === "error" && onRetry && upload.sourceFile && upload.errorKind !== "duplicate" && (
          <button
            className="row-action"
            aria-label={`Retry ${upload.filename}`}
            onClick={() => onRetry(upload.id)}
            type="button"
          >
            <RotateCcw size={16} />
          </button>
        )}
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
    </div>
  );
}
