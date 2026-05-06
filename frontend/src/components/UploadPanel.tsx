import { useEffect, useState } from "react";
import { Loader2, X } from "lucide-react";
import { useUpload } from "../hooks/useUpload";
import {
  deleteDocument,
  getDocumentOpenUrl,
  getParsedDocument,
  listDocuments,
  type ParsedDocumentSummary,
} from "../services/api";
import { useAppStore } from "../stores/appStore";
import DocumentList, { type StatusFilter } from "./upload/DocumentList";
import DocumentOverview from "./upload/DocumentOverview";
import UploadDropzone from "./upload/UploadDropzone";

function parsedHighlights(parsed: ParsedDocumentSummary) {
  const format = parsed.format.toLowerCase();
  const rows: Array<{ label: string; value: number | string }> = [
    { label: "Chunks", value: parsed.chunks_count },
    { label: "Sections", value: parsed.sections_count },
  ];

  if (format === "md") {
    rows.push(
      { label: "Headings", value: parsed.headers_count },
      { label: "Links", value: parsed.links_count },
      { label: "Images", value: parsed.images_count },
      { label: "Code blocks", value: parsed.code_blocks_count },
      { label: "List items", value: parsed.list_items_count },
    );
  } else if (format === "pdf") {
    return [
      { label: "Base text", value: `${parsed.word_count} words` },
      { label: "Pages", value: parsed.sections_count },
      { label: "Text chunks", value: parsed.chunks_count },
      { label: "Tables", value: parsed.tables_count > 0 ? parsed.tables_count : "None found" },
      { label: "Figures/images", value: parsed.images_count > 0 ? parsed.images_count : "Not extracted" },
      { label: "Reading order", value: "Basic" },
    ];
  } else if (format === "docx") {
    return [
      { label: "Text", value: `${parsed.word_count} words` },
      { label: "Pages", value: parsed.pages_count || "Unknown" },
      { label: "Paragraphs", value: parsed.paragraphs_count },
      { label: "Tables", value: parsed.tables_count > 0 ? parsed.tables_count : "None found" },
      { label: "Images", value: parsed.images_count > 0 ? parsed.images_count : "None found" },
      { label: "Comments", value: parsed.comments_count > 0 ? parsed.comments_count : "None found" },
      { label: "Style inheritance", value: parsed.inherited_styles_count > 0 ? parsed.inherited_styles_count : "Basic" },
    ];
  } else if (["py", "js", "ts"].includes(format)) {
    rows.push(
      { label: "Imports", value: parsed.imports_count },
      { label: "Functions", value: parsed.functions_count },
      { label: "Classes", value: parsed.classes_count },
      { label: "Code blocks", value: parsed.code_blocks_count },
    );
  } else if (format === "json") {
    rows.push({ label: "Schema blocks", value: parsed.sections_count });
  } else if (format === "csv") {
    rows.push({ label: "Tables", value: parsed.tables_count });
  } else if (["html", "htm"].includes(format)) {
    rows.push({ label: "Links", value: parsed.links_count });
  }

  return rows.filter(
    (row, index) => index < 2 || typeof row.value === "string" || row.value > 0,
  );
}

// Implemented: upload surface, backend document list, delete action, and parsed structure viewer.
export default function UploadPanel() {
  const [deleting, setDeleting] = useState<string | null>(null);
  const [filter, setFilter] = useState<StatusFilter>("all");
  const [parsed, setParsed] = useState<ParsedDocumentSummary | null>(null);
  const [parsedError, setParsedError] = useState("");
  const [parsedLabel, setParsedLabel] = useState("");
  const [parsedFilename, setParsedFilename] = useState("");
  const [loadingParsed, setLoadingParsed] = useState(false);
  const { uploads, uploadMany, dismissUpload } = useUpload();
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
      setParsedError("Parse result is not ready yet. Try again after upload finishes.");
    } finally {
      setLoadingParsed(false);
    }
  };

  const handleOpenFile = (filename: string) => {
    window.open(getDocumentOpenUrl(filename), "_blank", "noopener,noreferrer");
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
        onDismissUpload={dismissUpload}
        onOpenFile={handleOpenFile}
        onViewParsed={handleViewParsed}
      />
      {(loadingParsed || parsed || parsedError) && (
        <section className="parsed-viewer">
          <header>
            <div>
              <span className="section-heading">Parsed structure</span>
              <strong>{parsedLabel || "Parsed document"}</strong>
            </div>
            <button
              type="button"
              aria-label="Close parsed structure viewer"
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
            <>
              <div className="parsed-meta">
                <span>{parsed.format || "unknown"}</span>
                <span>{parsed.word_count} words</span>
                <span>{parsed.reading_time} min read</span>
              </div>
              <div className="parsed-highlights">
                {parsedHighlights(parsed).map((item) => (
                  <article className="parsed-highlight" key={item.label}>
                    <span>{item.label}</span>
                    <strong>{item.value}</strong>
                  </article>
                ))}
              </div>
              <div className="parsed-grid">
                <span>Sections <strong>{parsed.sections_count}</strong></span>
                <span>Chunks <strong>{parsed.chunks_count}</strong></span>
                {parsed.headers_count > 0 && <span>Headers <strong>{parsed.headers_count}</strong></span>}
                {parsed.links_count > 0 && <span>Links <strong>{parsed.links_count}</strong></span>}
                {parsed.images_count > 0 && <span>Images <strong>{parsed.images_count}</strong></span>}
                {parsed.list_items_count > 0 && <span>Lists <strong>{parsed.list_items_count}</strong></span>}
                {parsed.code_blocks_count > 0 && <span>Code <strong>{parsed.code_blocks_count}</strong></span>}
                {parsed.tables_count > 0 && <span>Tables <strong>{parsed.tables_count}</strong></span>}
                {parsed.pages_count > 0 && <span>Pages <strong>{parsed.pages_count}</strong></span>}
                {parsed.paragraphs_count > 0 && <span>Paragraphs <strong>{parsed.paragraphs_count}</strong></span>}
                {parsed.comments_count > 0 && <span>Comments <strong>{parsed.comments_count}</strong></span>}
                {parsed.inherited_styles_count > 0 && <span>Style inheritance <strong>{parsed.inherited_styles_count}</strong></span>}
                {parsed.imports_count > 0 && <span>Imports <strong>{parsed.imports_count}</strong></span>}
                {parsed.functions_count > 0 && <span>Functions <strong>{parsed.functions_count}</strong></span>}
                {parsed.classes_count > 0 && <span>Classes <strong>{parsed.classes_count}</strong></span>}
                {parsed.entities_count > 0 && <span>Entities <strong>{parsed.entities_count}</strong></span>}
                {parsed.languages.length > 0 && <span>Languages <strong>{parsed.languages.join(", ")}</strong></span>}
                {parsed.imports.length > 0 && <span>Import names <strong>{parsed.imports.join(", ")}</strong></span>}
                {parsed.functions.length > 0 && <span>Function names <strong>{parsed.functions.join(", ")}</strong></span>}
                {parsed.classes.length > 0 && <span>Class names <strong>{parsed.classes.join(", ")}</strong></span>}
              </div>
            </>
          )}
        </section>
      )}
    </div>
  );
}
