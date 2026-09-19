import { ChevronLeft, ChevronRight, ExternalLink, FileSearch, X } from "lucide-react";
import { useMemo, useState } from "react";
import { getDocumentOpenUrl } from "../../services/api";
import type {
  ComparisonDocument,
  ComparisonEvidence,
  ComparisonFinding,
  ComparisonMethod,
  ComparisonPreview,
} from "../../services/api";

interface Props {
  preview: ComparisonPreview;
  workspaceId: string;
}

const METHOD_LABELS: Array<[keyof ComparisonDocument["methods"], string]> = [
  ["design", "Study design"],
  ["population", "Population"],
  ["human_animal_in_vitro", "Human / animal / in vitro"],
  ["sample_size", "Sample size"],
  ["comparator", "Comparator"],
];

function supportLabel(method: ComparisonMethod) {
  if (method.support_status === "not_reported") return "Not reported";
  if (method.support_status === "source_unavailable") return "Source unavailable";
  if (method.support_status === "partially_supported") return "Partially supported";
  if (method.support_status === "uncertain") return "Uncertain";
  return "Supported";
}

function coverageLabel(document: ComparisonDocument) {
  if (document.coverage_status === "complete") return "Coverage complete";
  if (document.coverage_status === "partial") return "Coverage partial";
  return "Coverage unknown";
}

function EvidenceButton({
  evidence,
  onOpen,
}: {
  evidence: ComparisonEvidence[];
  onOpen: (items: ComparisonEvidence[]) => void;
}) {
  if (!evidence.length) return null;
  return (
    <button
      type="button"
      className="disease-comparison-evidence-button"
      onClick={() => onOpen(evidence)}
    >
      <FileSearch size={13} />
      View evidence ({evidence.length})
    </button>
  );
}

function FindingList({
  title,
  items,
  onOpenEvidence,
}: {
  title: string;
  items: ComparisonFinding[];
  onOpenEvidence: (items: ComparisonEvidence[]) => void;
}) {
  return (
    <section className="disease-comparison-subsection">
      <div className="disease-comparison-section-heading">
        <h4>{title}</h4>
        <span>{items.length}</span>
      </div>
      {!items.length && <p className="disease-comparison-muted">No cited items available.</p>}
      {items.map((item) => (
        <article className="disease-comparison-finding" key={item.id}>
          <strong>{item.statement}</strong>
          {item.explanation && <p>{item.explanation}</p>}
          <EvidenceButton evidence={item.evidence} onOpen={onOpenEvidence} />
        </article>
      ))}
    </section>
  );
}

function ComparisonSourceDrawer({
  evidenceItems,
  evidenceIndex,
  document,
  workspaceId,
  onClose,
  onChangeEvidence,
}: {
  evidenceItems: ComparisonEvidence[];
  evidenceIndex: number;
  document: ComparisonDocument | undefined;
  workspaceId: string;
  onClose: () => void;
  onChangeEvidence: (index: number) => void;
}) {
  const evidence = evidenceItems[evidenceIndex];
  const openUrl = document
    ? getDocumentOpenUrl(document.open_filename, workspaceId)
    : "";
  return (
    <div
      className="disease-source-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <aside
        className="disease-source-drawer"
        role="dialog"
        aria-modal="true"
        aria-label="Comparison evidence source"
      >
        <div className="disease-source-heading">
          <div>
            <span className="disease-profile-eyebrow">Comparison evidence</span>
            <h3>{document?.title || evidence.document_id}</h3>
          </div>
          <button
            type="button"
            className="disease-icon-button"
            aria-label="Close comparison evidence"
            onClick={onClose}
          >
            <X size={18} />
          </button>
        </div>
        <div className="disease-source-meta">
          <span>{evidence.section_title || evidence.section_type}</span>
          {evidence.page_start && (
            <span>
              Page {evidence.page_start}
              {evidence.page_end && evidence.page_end !== evidence.page_start
                ? `-${evidence.page_end}`
                : ""}
            </span>
          )}
          <span>Evidence {evidence.evidence_id}</span>
          <span>Run {evidence.analysis_run_id}</span>
        </div>
        <blockquote className="disease-comparison-drawer-quote">{evidence.quote}</blockquote>
        <div className="disease-comparison-evidence-nav" aria-label="Comparison evidence navigation">
          <button
            type="button"
            className="disease-icon-button"
            aria-label="Previous evidence"
            title="Previous evidence"
            disabled={evidenceIndex === 0}
            onClick={() => onChangeEvidence(evidenceIndex - 1)}
          >
            <ChevronLeft size={16} />
          </button>
          <span>Evidence {evidenceIndex + 1} / {evidenceItems.length}</span>
          <button
            type="button"
            className="disease-icon-button"
            aria-label="Next evidence"
            title="Next evidence"
            disabled={evidenceIndex >= evidenceItems.length - 1}
            onClick={() => onChangeEvidence(evidenceIndex + 1)}
          >
            <ChevronRight size={16} />
          </button>
        </div>
        {openUrl && (
          <a
            className="disease-comparison-open-source"
            href={openUrl}
            target="_blank"
            rel="noreferrer noopener"
          >
            Open source document <ExternalLink size={13} />
          </a>
        )}
      </aside>
    </div>
  );
}

export default function DiseaseComparisonPanel({ preview, workspaceId }: Props) {
  const [selectedEvidence, setSelectedEvidence] = useState<{
    items: ComparisonEvidence[];
    index: number;
  } | null>(null);
  const documentsById = useMemo(
    () => new Map(preview.documents.map((document) => [document.document_id, document])),
    [preview.documents],
  );
  const activeEvidence = selectedEvidence?.items[selectedEvidence.index];
  const selectedDocument = activeEvidence
    ? documentsById.get(activeEvidence.document_id)
    : undefined;

  return (
    <section className="disease-comparison-panel" aria-label="Document comparison preview">
      <div className="disease-comparison-heading">
        <div>
          <span className="disease-profile-eyebrow">Evidence comparison</span>
          <h2>Compare selected sources</h2>
          <p>Methods, reported findings, and limitations are shown per document. No overall ranking is generated.</p>
        </div>
        <span className="disease-comparison-count">{preview.documents.length} sources</span>
      </div>
      {preview.warnings.map((warning) => (
        <p className="disease-profile-warning" key={warning}>{warning}</p>
      ))}
      <div className="disease-comparison-document-grid">
        {preview.documents.map((document) => (
          <article className="disease-comparison-document" key={document.document_id}>
            <header className="disease-comparison-document-header">
              <div>
                <h3>{document.title}</h3>
                <span>
                  {document.document_kind}
                  {document.document_date ? ` · ${document.document_date}` : ""}
                </span>
              </div>
              <a
                className="disease-icon-button"
                href={getDocumentOpenUrl(document.open_filename, workspaceId)}
                target="_blank"
                rel="noreferrer noopener"
                aria-label={`Open ${document.title}`}
                title="Open source document"
              >
                <ExternalLink size={15} />
              </a>
            </header>
            <p className={`disease-comparison-coverage ${document.coverage_status}`}>
              {coverageLabel(document)}
              {document.coverage.total_chunks > 0
                ? ` · ${document.coverage.selected_chunks}/${document.coverage.total_chunks} chunks`
                : ""}
            </p>
            <section className="disease-comparison-methods">
              <div className="disease-comparison-section-heading"><h4>Study methods</h4></div>
              {METHOD_LABELS.map(([field, label]) => {
                const method = document.methods[field];
                return (
                  <div className="disease-comparison-method" key={field}>
                    <span>{label}</span>
                    <strong>{method.value || "Not reported in source analysis."}</strong>
                    <small>{supportLabel(method)}</small>
                    <EvidenceButton
                      evidence={method.evidence}
                      onOpen={(items) => setSelectedEvidence({ items, index: 0 })}
                    />
                  </div>
                );
              })}
            </section>
            <FindingList
              title="Reported findings"
              items={document.findings}
              onOpenEvidence={(items) => setSelectedEvidence({ items, index: 0 })}
            />
            {document.findings_truncated && (
              <p className="disease-comparison-truncation">
                Showing {document.findings.length} of {document.findings_total} findings. Open the single-document report for the remaining items.
              </p>
            )}
            <FindingList
              title="Limitations"
              items={document.limitations}
              onOpenEvidence={(items) => setSelectedEvidence({ items, index: 0 })}
            />
            {document.limitations_truncated && (
              <p className="disease-comparison-truncation">
                Showing {document.limitations.length} of {document.limitations_total} limitations. Open the single-document report for the remaining items.
              </p>
            )}
          </article>
        ))}
      </div>
      {preview.discussion_questions.length > 0 && (
        <section className="disease-comparison-questions">
          <div className="disease-comparison-section-heading"><h3>Questions to discuss with a clinician</h3></div>
          {preview.discussion_questions.map((item) => (
            <article key={item.id}>
              <strong>{item.question}</strong>
              <p>{item.rationale}</p>
              <EvidenceButton
                evidence={item.evidence}
                onOpen={(items) => setSelectedEvidence({ items, index: 0 })}
              />
            </article>
          ))}
        </section>
      )}
      {selectedEvidence && activeEvidence && (
        <ComparisonSourceDrawer
          evidenceItems={selectedEvidence.items}
          evidenceIndex={selectedEvidence.index}
          document={selectedDocument}
          workspaceId={workspaceId}
          onClose={() => setSelectedEvidence(null)}
          onChangeEvidence={(index) => setSelectedEvidence((current) => (
            current ? { ...current, index } : current
          ))}
        />
      )}
    </section>
  );
}
