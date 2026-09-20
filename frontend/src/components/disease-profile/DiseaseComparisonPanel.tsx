import { ChevronLeft, ChevronRight, ExternalLink, FileSearch, X } from "lucide-react";
import { useMemo, useState } from "react";
import { getDocumentOpenUrl } from "../../services/api";
import type {
  ComparisonDocument,
  ComparisonEvidence,
  ComparisonFinding,
  ComparisonLanguage,
  ComparisonPreview,
} from "../../services/api";
import {
  getComparisonMessages,
  type ComparisonMessages,
  type ComparisonMethodKey,
} from "./comparisonMessages";

interface Props {
  preview: ComparisonPreview;
  workspaceId: string;
  language?: ComparisonLanguage;
}

const METHOD_FIELDS: ComparisonMethodKey[] = [
  "design",
  "population",
  "human_animal_in_vitro",
  "sample_size",
  "comparator",
];

function EvidenceButton({
  evidence,
  label,
  onOpen,
}: {
  evidence: ComparisonEvidence[];
  label: string;
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
      {label}
    </button>
  );
}

function FindingList({
  title,
  items,
  emptyLabel,
  evidenceLabel,
  evidenceTruncatedLabel,
  onOpenEvidence,
}: {
  title: string;
  items: ComparisonFinding[];
  emptyLabel: string;
  evidenceLabel: (count: number) => string;
  evidenceTruncatedLabel: (shown: number, total: number) => string;
  onOpenEvidence: (items: ComparisonEvidence[]) => void;
}) {
  return (
    <section className="disease-comparison-subsection">
      <div className="disease-comparison-section-heading">
        <h4>{title}</h4>
        <span>{items.length}</span>
      </div>
      {!items.length && <p className="disease-comparison-muted">{emptyLabel}</p>}
      {items.map((item) => (
        <article className="disease-comparison-finding" key={item.id}>
          <strong>{item.statement}</strong>
          {item.explanation && <p>{item.explanation}</p>}
          <EvidenceButton
            evidence={item.evidence}
            label={evidenceLabel(item.evidence.length)}
            onOpen={onOpenEvidence}
          />
          {item.evidence_truncated && (
            <p className="disease-comparison-evidence-truncation">
              {evidenceTruncatedLabel(item.evidence.length, item.evidence_total)}
            </p>
          )}
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
  messages,
  onClose,
  onChangeEvidence,
}: {
  evidenceItems: ComparisonEvidence[];
  evidenceIndex: number;
  document: ComparisonDocument | undefined;
  workspaceId: string;
  messages: ComparisonMessages;
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
        aria-label={messages.evidenceSource}
      >
        <div className="disease-source-heading">
          <div>
            <span className="disease-profile-eyebrow">{messages.evidenceSource}</span>
            <h3>{document?.title || evidence.document_id}</h3>
          </div>
          <button
            type="button"
            className="disease-icon-button"
            aria-label={messages.closeEvidence}
            onClick={onClose}
          >
            <X size={18} />
          </button>
        </div>
        <div className="disease-source-meta">
          <span>{evidence.section_title || evidence.section_type}</span>
          {evidence.page_start && (
            <span>{messages.page(evidence.page_start, evidence.page_end)}</span>
          )}
          <span>{messages.evidenceId(evidence.evidence_id)}</span>
          <span>{messages.runId(evidence.analysis_run_id)}</span>
        </div>
        <blockquote className="disease-comparison-drawer-quote">{evidence.quote}</blockquote>
        {evidence.quote_truncated && (
          <p className="disease-comparison-quote-warning">
            {messages.excerptWarning}
          </p>
        )}
        <div className="disease-comparison-evidence-nav" aria-label={messages.evidenceNavigation}>
          <button
            type="button"
            className="disease-icon-button"
            aria-label={messages.previousEvidence}
            title={messages.previousEvidence}
            disabled={evidenceIndex === 0}
            onClick={() => onChangeEvidence(evidenceIndex - 1)}
          >
            <ChevronLeft size={16} />
          </button>
          <span>{messages.evidencePosition(evidenceIndex + 1, evidenceItems.length)}</span>
          <button
            type="button"
            className="disease-icon-button"
            aria-label={messages.nextEvidence}
            title={messages.nextEvidence}
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
            {messages.openSource} <ExternalLink size={13} />
          </a>
        )}
      </aside>
    </div>
  );
}

export default function DiseaseComparisonPanel({ preview, workspaceId, language = "en" }: Props) {
  const messages = getComparisonMessages(language);
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
    <section className="disease-comparison-panel" aria-label={messages.title}>
      <div className="disease-comparison-heading">
        <div>
          <span className="disease-profile-eyebrow">{messages.eyebrow}</span>
          <h2>{messages.title}</h2>
          <p>{messages.description}</p>
        </div>
        <span className="disease-comparison-count">{messages.sourceCount(preview.documents.length)}</span>
      </div>
      <p className="disease-comparison-language-notice">{messages.languageNotice}</p>
      {preview.warnings.map((warning) => (
        <p className="disease-profile-warning" key={warning}>{messages.warning(warning)}</p>
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
              {messages.coverageStatus[document.coverage_status]}
              {document.coverage.total_chunks > 0
                ? ` · ${messages.chunks(document.coverage.selected_chunks, document.coverage.total_chunks)}`
                : ""}
            </p>
            <section className="disease-comparison-methods">
              <div className="disease-comparison-section-heading"><h4>{messages.methods}</h4></div>
              {METHOD_FIELDS.map((field) => {
                const method = document.methods[field];
                return (
                  <div className="disease-comparison-method" key={field}>
                    <span>{messages.methodLabels[field]}</span>
                    <strong>
                      {method.value || (
                        method.support_status === "source_unavailable"
                          ? messages.sourceUnavailableValue
                          : messages.notReportedValue
                      )}
                    </strong>
                    <small>{messages.supportStatus[method.support_status]}</small>
                    <EvidenceButton
                      evidence={method.evidence}
                      label={messages.viewEvidence(method.evidence.length)}
                      onOpen={(items) => setSelectedEvidence({ items, index: 0 })}
                    />
                    {method.evidence_truncated && (
                      <p className="disease-comparison-evidence-truncation">
                        {messages.evidenceTruncated(method.evidence.length, method.evidence_total)}
                      </p>
                    )}
                  </div>
                );
              })}
            </section>
            <FindingList
              title={messages.findings}
              items={document.findings}
              emptyLabel={messages.noCitedItems}
              evidenceLabel={messages.viewEvidence}
              evidenceTruncatedLabel={messages.evidenceTruncated}
              onOpenEvidence={(items) => setSelectedEvidence({ items, index: 0 })}
            />
            {document.findings_truncated && (
              <p className="disease-comparison-truncation">
                {messages.findingsTruncated(document.findings.length, document.findings_total)}
              </p>
            )}
            <FindingList
              title={messages.limitations}
              items={document.limitations}
              emptyLabel={messages.noCitedItems}
              evidenceLabel={messages.viewEvidence}
              evidenceTruncatedLabel={messages.evidenceTruncated}
              onOpenEvidence={(items) => setSelectedEvidence({ items, index: 0 })}
            />
            {document.limitations_truncated && (
              <p className="disease-comparison-truncation">
                {messages.limitationsTruncated(document.limitations.length, document.limitations_total)}
              </p>
            )}
          </article>
        ))}
      </div>
      {preview.discussion_questions.length > 0 && (
        <section className="disease-comparison-questions">
          <div className="disease-comparison-section-heading"><h3>{messages.questions}</h3></div>
          {preview.discussion_questions.map((item) => (
            <article key={item.id}>
              <strong>{item.question}</strong>
              <p>{item.rationale}</p>
              <EvidenceButton
                evidence={item.evidence}
                label={messages.viewEvidence(item.evidence.length)}
                onOpen={(items) => setSelectedEvidence({ items, index: 0 })}
              />
              {item.evidence_truncated && (
                <p className="disease-comparison-evidence-truncation">
                  {messages.evidenceTruncated(item.evidence.length, item.evidence_total)}
                </p>
              )}
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
          messages={messages}
          onClose={() => setSelectedEvidence(null)}
          onChangeEvidence={(index) => setSelectedEvidence((current) => (
            current ? { ...current, index } : current
          ))}
        />
      )}
    </section>
  );
}
