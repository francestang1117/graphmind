import { useEffect, useMemo, useState } from "react";
import { Loader2, X } from "lucide-react";
import { useUpload } from "../hooks/useUpload";
import {
  deleteDocument,
  getParsedDocument,
  listDocuments,
  type ParsedMarkdownSummary,
} from "../services/api";
import { useAppStore } from "../stores/appStore";
import { demoFiles } from "../utils/fileMeta";
import DocumentList, { type StatusFilter } from "./upload/DocumentList";
import DocumentOverview from "./upload/DocumentOverview";
import UploadDropzone from "./upload/UploadDropzone";

// Implemented: upload surface, backend document list, delete action, and Markdown summary viewer.
export default function UploadPanel() {
  const [deleting, setDeleting] = useState<string | null>(null);
  const [filter, setFilter] = useState<StatusFilter>("all");
  const [parsed, setParsed] = useState<ParsedMarkdownSummary | null>(null);
  const [parsedError, setParsedError] = useState("");
  const [loadingParsed, setLoadingParsed] = useState(false);
  const { uploads, uploadMany } = useUpload();
  const { files, setFiles, removeFile } = useAppStore();

  useEffect(() => {
    // Treat the backend as the source of truth, but fall back quietly for demos.
    listDocuments()
      .then(setFiles)
      .catch(() => setFiles([]));
  }, [setFiles]);

  const shownFiles = useMemo(() => {
    if (files.length) return files;
    if (uploads.length) return [];
    return demoFiles;
  }, [files, uploads.length]);

  const handleDelete = async (filename: string) => {
    setDeleting(filename);
    try {
      await deleteDocument(filename);
      removeFile(filename);
    } finally {
      setDeleting(null);
    }
  };

  const handleViewParsed = async (filename: string) => {
    setLoadingParsed(true);
    setParsedError("");
    try {
      setParsed(await getParsedDocument(filename));
    } catch {
      setParsed(null);
      setParsedError("Markdown parse result is not ready yet. Try again after upload finishes.");
    } finally {
      setLoadingParsed(false);
    }
  };

  return (
    <div className="documents-panel">
      <UploadDropzone onFiles={uploadMany} />
      <DocumentOverview files={shownFiles} uploads={uploads} />
      <DocumentList
        files={shownFiles}
        uploads={uploads}
        filter={filter}
        demo={files.length === 0}
        deleting={deleting}
        onFilterChange={setFilter}
        onDelete={handleDelete}
        onViewParsed={handleViewParsed}
      />
      {(loadingParsed || parsed || parsedError) && (
        <section className="parsed-viewer">
          <header>
            <div>
              <span className="section-heading">Markdown structure</span>
              <strong>{parsed?.title ?? "Parsed Markdown"}</strong>
            </div>
            <button
              type="button"
              aria-label="Close parsed Markdown viewer"
              onClick={() => {
                setParsed(null);
                setParsedError("");
              }}
            >
              <X size={17} />
            </button>
          </header>
          {loadingParsed && (
            <div className="parsed-state">
              <Loader2 className="spin" size={18} />
              Loading parse summary...
            </div>
          )}
          {parsedError && <div className="parsed-state error">{parsedError}</div>}
          {parsed && (
            <div className="parsed-grid">
              <span>Headers <strong>{parsed.headers_count}</strong></span>
              <span>Sections <strong>{parsed.sections_count}</strong></span>
              <span>Links <strong>{parsed.links_count}</strong></span>
              <span>Images <strong>{parsed.images_count}</strong></span>
              <span>Code blocks <strong>{parsed.code_blocks_count}</strong></span>
              <span>Words <strong>{parsed.word_count}</strong></span>
              <span>Reading <strong>{parsed.reading_time} min</strong></span>
              <span>Languages <strong>{parsed.languages.join(", ") || "none"}</strong></span>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
