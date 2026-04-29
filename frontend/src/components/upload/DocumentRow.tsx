import { AlertCircle, CheckCircle2, Eye, EyeOff, Loader2, Trash2 } from "lucide-react";
import type { FileInfo } from "../../stores/appStore";
import { displayName, fileStatusLabel, formatDate, formatSize } from "../../utils/fileMeta";
import FileIcon from "./FileIcon";

interface Props {
  file: FileInfo & { progress?: number };
  demo?: boolean;
  deleting: boolean;
  parsedActive?: boolean;
  onDelete: (filename: string) => void;
  onViewParsed?: (filename: string, label: string) => void;
}

const PARSEABLE_EXTENSIONS = new Set([
  ".md",
  ".txt",
  ".pdf",
  ".docx",
  ".py",
  ".js",
  ".ts",
  ".json",
  ".csv",
  ".html",
  ".htm",
]);

// Implemented: icon, filename, size/date metadata, status pill, delete action, and parsed-structure action.
export default function DocumentRow({
  file,
  demo = false,
  deleting,
  parsedActive = false,
  onDelete,
  onViewParsed,
}: Props) {
  // Demo rows look real, but stay read-only so users do not delete sample data.
  const status = file.status ?? "done";
  const canViewParsed = !demo && PARSEABLE_EXTENSIONS.has(file.file_extension) && onViewParsed;

  return (
    <div className={`document-row ${demo ? "demo-row" : ""}`}>
      <FileIcon ext={file.file_extension} />
      <div className="document-main">
        <strong>{displayName(file)}</strong>
        <span>
          {formatSize(file.file_size)} · {formatDate(file.created_at)}
        </span>
        {status === "processing" && (
          <div className="row-progress">
            <div style={{ width: `${file.progress ?? 55}%` }} />
          </div>
        )}
      </div>
      <span className={`status-pill ${status}`}>
        {status === "processing" && <Loader2 className="spin" size={13} />}
        {status === "done" && <CheckCircle2 size={13} />}
        {status === "error" && <AlertCircle size={13} />}
        {fileStatusLabel(status)}
      </span>
      {canViewParsed && (
        <button
          className={`row-action ${parsedActive ? "active" : ""}`}
          aria-label={`${parsedActive ? "Hide" : "View"} parsed structure for ${displayName(file)}`}
          aria-pressed={parsedActive}
          onClick={() => onViewParsed(file.filename, displayName(file))}
        >
          {parsedActive ? <EyeOff size={17} /> : <Eye size={17} />}
        </button>
      )}
      {!demo && (
        <button
          className="row-action"
          aria-label={`Delete ${displayName(file)}`}
          onClick={() => onDelete(file.filename)}
          disabled={deleting}
        >
          {deleting ? <Loader2 className="spin" size={17} /> : <Trash2 size={17} />}
        </button>
      )}
    </div>
  );
}
