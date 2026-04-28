import { useRef, useState } from "react";
import { UploadCloud } from "lucide-react";

interface Props {
  onFiles: (files: FileList) => void;
}

// Implemented: drag-and-drop upload, click-to-browse, multi-file selection, and accepted extension hints.
export default function UploadDropzone({ onFiles }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  const handleDrop = (event: React.DragEvent<HTMLDivElement>) => {
    // Keep drag handling here so the upload hook only deals with files.
    event.preventDefault();
    setDragging(false);
    if (event.dataTransfer.files.length) onFiles(event.dataTransfer.files);
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
      <button type="button">Choose files</button>
      <input
        ref={inputRef}
        type="file"
        multiple
        accept=".md,.pdf,.txt,.docx,.py,.js,.ts"
        onChange={(event) => event.target.files && onFiles(event.target.files)}
      />
    </div>
  );
}
