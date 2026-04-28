import { useRef, useState } from "react";
import { UploadCloud } from "lucide-react";

interface Props {
  onFiles: (files: FileList | File[]) => void;
}

const allowedExtensions = new Set([".md", ".pdf", ".txt", ".docx", ".py", ".js", ".ts"]);
const accept = ".md,.pdf,.txt,.docx,.py,.js,.ts";
const supportedLabel = ".md, .pdf, .txt, .docx, .py, .js, .ts";

function fileExtension(filename: string) {
  return filename.includes(".") ? `.${filename.split(".").pop()?.toLowerCase() ?? ""}` : "";
}

// Implemented: drag-and-drop upload, click-to-browse, multi-file selection, and accepted extension hints.
export default function UploadDropzone({ onFiles }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [notice, setNotice] = useState("");

  const acceptFiles = (files: FileList | File[]) => {
    // Unsupported files are rejected at the doorway, not shown as failed uploads.
    const incoming = Array.from(files);
    const accepted = incoming.filter((file) => allowedExtensions.has(fileExtension(file.name)));
    const rejected = incoming.length - accepted.length;

    if (rejected) {
      setNotice(
        rejected === 1
          ? `That file type is not supported. Use ${supportedLabel}.`
          : `${rejected} files were skipped. Supported types: ${supportedLabel}.`,
      );
    } else {
      setNotice("");
    }

    if (accepted.length) onFiles(accepted);
  };

  const handleDrop = (event: React.DragEvent<HTMLDivElement>) => {
    // Keep drag handling here so the upload hook only deals with files.
    event.preventDefault();
    setDragging(false);
    if (event.dataTransfer.files.length) acceptFiles(event.dataTransfer.files);
  };

  return (
    <div
      className={`dropzone ${dragging ? "dragging" : ""}`}
      onDragEnter={(event) => {
        event.preventDefault();
        setDragging(true);
      }}
      onDragLeave={(event) => {
        event.preventDefault();
        setDragging(false);
      }}
      onDragOver={(event) => event.preventDefault()}
      onDrop={handleDrop}
      onClick={() => inputRef.current?.click()}
    >
      <UploadCloud size={56} />
      <strong>{dragging ? "Release to upload" : "Drop files here or click to browse"}</strong>
      <span>Supports .md, .pdf, .txt, .docx, .py, .js, .ts</span>
      {notice && <small className="dropzone-notice">{notice}</small>}
      <button type="button">Choose files</button>
      <input
        ref={inputRef}
        type="file"
        multiple
        accept={accept}
        onChange={(event) => {
          if (event.target.files) acceptFiles(event.target.files);
          // Let users choose the same file again after clearing a warning.
          event.target.value = "";
        }}
      />
    </div>
  );
}
