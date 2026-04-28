import { useEffect, useState } from "react";
import { Loader2, X } from "lucide-react";
import { useUpload } from "../hooks/useUpload";
import {
  deleteDocument,
  getParsedDocument,
  listDocuments,
  type ParsedMarkdownSummary,
} from "../services/api";
import { useAppStore } from "../stores/appStore";
import DocumentList, { type StatusFilter } from "./upload/DocumentList";
import DocumentOverview from "./upload/DocumentOverview";
import UploadDropzone from "./upload/UploadDropzone";

// Implemented: upload surface, backend document list, delete action, and Markdown summary viewer.
export default function UploadPanel() {
  const [deleting, setDeleting] = useState<string | null>(null);
  const [filter, setFilter] = useState<StatusFilter>("all");
  const [parsed, setParsed] = useState<ParsedMarkdownSummary | null>(null);
  const [parsedError, setParsedError] = useState("");
  const [parsedLabel, setParsedLabel] = useState("");
  const [parsedFilename, setParsedFilename] = useState("");
  const [loadingParsed, setLoadingParsed] = useState(false);
  const { uploads, uploadMany } = useUpload();
  const { files, setFiles, removeFile } = useAppStore();

  useEffect(() => {
    // Treat the backend as the source of truth, but fall back quietly for demos.
    listDocuments()
      .then(setFiles)
      .catch(() => setFiles([]));
  }, [setFiles]);

  const handleDelete = async (filename: string) => {
    setDeleting(filename);
    try {
      await deleteDocument(filename);
      removeFile(filename);
      if (parsedFilename === filename) {
        setParsed(null);
        setParsedError("");
        setParsedLabel("");
        setParsedFilename("");
      }
    } finally {
      setDeleting(null);
    }
  };

  const handleViewParsed = async (filename: string, label: string) => {
    if (parsedFilename === filename && (loadingParsed || parsed || parsedError)) {
      setParsed(null);
      setParsedError("");
      setParsedLabel("");
      setParsedFilename("");
      return;
    }

    setParsed(null);
    setLoadingParsed(true);
    setParsedError("");
    setParsedLabel(label);
    setParsedFilename(filename);
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
      <DocumentOverview files={files} uploads={uploads} />
      <DocumentList
        files={files}
        uploads={uploads}
        filter={filter}
        demo={false}
        deleting={deleting}
        activeParsedFilename={parsedFilename}
        onFilterChange={setFilter}
        onDelete={handleDelete}
        onViewParsed={handleViewParsed}
      />
      {(loadingParsed || parsed || parsedError) && (
        <section className="parsed-viewer">
          <header>
            <div>
              <span className="section-heading">Markdown structure</span>
              <strong>{parsedLabel || "Parsed Markdown"}</strong>
            </div>
            <button
              type="button"
              aria-label="Close parsed Markdown viewer"
              onClick={() => {
                setParsed(null);
                setParsedError("");
                setParsedLabel("");
                setParsedFilename("");
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
              <span>Title <strong>{parsed.title || "none"}</strong></span>
              <span>Languages <strong>{parsed.languages.join(", ") || "none"}</strong></span>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
