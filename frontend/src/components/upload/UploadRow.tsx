import { AlertCircle, CheckCircle2, Loader2 } from "lucide-react";
import type { UploadState } from "../../hooks/useUpload";
import { formatSize } from "../../utils/fileMeta";
import FileIcon from "./FileIcon";

function uploadStatusLabel(upload: UploadState) {
  // The label mirrors the backend pipeline names without exposing internals.
  if (upload.status === "error") return "Error";
  if (upload.status === "done") return "Done";
  if (upload.progress >= 80 || upload.step === "Indexing") return "Indexing";
  return `${upload.progress}%`;
}

// Implemented: temporary upload row with progress, pipeline step label, and error state.
export default function UploadRow({ upload }: { upload: UploadState }) {
  const statusClass =
    upload.status === "error"
      ? "error"
      : upload.status === "uploading"
        ? "processing"
        : "done";

  return (
    <div className="document-row upload-row">
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
    </div>
  );
}
