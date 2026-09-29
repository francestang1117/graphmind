import { ExternalLink, X } from "lucide-react";
import type { DiseaseProfileDocument, DiseaseProfileItem } from "../../services/api";

interface Props {
  item: DiseaseProfileItem;
  onClose: () => void;
  relatedDocuments?: DiseaseProfileDocument[];
  relatedDocumentsLoading?: boolean;
  relatedDocumentsError?: unknown;
  relatedDocumentsHasMore?: boolean;
  relatedDocumentsLoadingMore?: boolean;
  onLoadMoreRelatedDocuments?: () => void;
  onRetryRelatedDocuments?: () => void;
}

export default function DiseaseSourceDrawer({
  item,
  onClose,
  relatedDocuments = [],
  relatedDocumentsLoading = false,
  relatedDocumentsError,
  relatedDocumentsHasMore = false,
  relatedDocumentsLoadingMore = false,
  onLoadMoreRelatedDocuments,
  onRetryRelatedDocuments,
}: Props) {
  const isExternalArticle = item.item_type === "article";
  const heading = isExternalArticle
    ? item.title || `${item.source.toUpperCase()} ${item.external_id}`
    : item.document_title || item.title || "External study";
  return (
    <div className="disease-source-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <aside className="disease-source-drawer" role="dialog" aria-modal="true" aria-label="Evidence source">
        <div className="disease-source-heading">
          <div>
            <span className="disease-profile-eyebrow">Source details</span>
            <h3>{heading}</h3>
          </div>
          <button type="button" className="disease-icon-button" aria-label="Close source details" onClick={onClose}>
            <X size={18} />
          </button>
        </div>
        <div className="disease-source-meta">
          <span>{isExternalArticle ? item.source.toUpperCase() : item.document_kind || "Source"}</span>
          {item.document_date && <span>{item.document_date}</span>}
          {item.analysis_run_id && <span>Analysis {item.analysis_run_id.slice(0, 12)}</span>}
          {isExternalArticle && item.external_id && <span>{item.external_id}</span>}
          <span className={`disease-source-status ${item.source_status}`}>{item.source_status}</span>
        </div>
        {isExternalArticle && item.document_title && (
          <p className="disease-source-context">Found through {item.document_title}</p>
        )}
        {isExternalArticle && (
          <section className="disease-source-related-documents">
            <div className="disease-source-related-heading">
              <strong>Linked research documents</strong>
              <span>{item.related_document_count}</span>
            </div>
            {relatedDocumentsLoading && <p className="disease-profile-section-loading">Loading linked documents...</p>}
            {Boolean(relatedDocumentsError) && !relatedDocumentsLoading && (
              <div className="disease-profile-inline-error" role="alert">
                <span>Could not load linked documents.</span>
                <button type="button" onClick={onRetryRelatedDocuments}>Retry</button>
              </div>
            )}
            {!relatedDocumentsLoading && !relatedDocumentsError && !relatedDocuments.length && (
              <p className="disease-source-empty">No current linked document is available.</p>
            )}
            {relatedDocuments.map((document) => (
              <div className="disease-source-related-document" key={document.document_id}>
                <strong>{document.title}</strong>
                <span>{document.document_kind} · {document.source_status}{document.document_date ? ` · ${document.document_date}` : ""}</span>
              </div>
            ))}
            {relatedDocumentsHasMore && (
              <button type="button" className="disease-profile-load-more" onClick={onLoadMoreRelatedDocuments} disabled={relatedDocumentsLoadingMore}>
                {relatedDocumentsLoadingMore ? "Loading..." : "Load more linked documents"}
              </button>
            )}
            {item.related_documents_truncated
              && !relatedDocumentsHasMore
              && !relatedDocumentsError
              && relatedDocuments.length < item.related_document_count && (
              <p className="disease-profile-warning">Some linked documents are available through the source list.</p>
            )}
          </section>
        )}
        {item.text && <p className="disease-source-main-text">{item.text}</p>}
        {item.explanation && <p className="disease-source-explanation">{item.explanation}</p>}
        {item.value && <p className="disease-source-main-text"><strong>{item.title}: </strong>{item.value}</p>}
        {item.question && <p className="disease-source-main-text"><strong>{item.question}</strong></p>}
        {item.evidence_truncated && (
          <p className="disease-profile-warning">
            Showing {item.evidence.length} of {item.evidence_total} evidence sources.
          </p>
        )}
        {item.evidence.map((source) => (
          <article
            className="disease-source-quote"
            key={[
              source.document_id ?? "no-document",
              source.analysis_run_id ?? "no-run",
              source.evidence_id ?? source.external_id ?? "no-evidence",
              source.section_title,
              source.page_start ?? "no-page",
            ].join(":")}
          >
            <div className="disease-source-quote-meta">
              <span>{source.document_title || source.source || "Source"}</span>
              {source.page_start && <span>Page {source.page_start}{source.page_end && source.page_end !== source.page_start ? `–${source.page_end}` : ""}</span>}
              {source.section_title && <span>{source.section_title}</span>}
            </div>
            {source.quote && <blockquote>{source.quote}</blockquote>}
            {source.external_id && <span className="disease-source-external-id">{source.source.toUpperCase()} {source.external_id}</span>}
            {source.source_url && (
              <a href={source.source_url} target="_blank" rel="noreferrer noopener">
                Open public source <ExternalLink size={13} />
              </a>
            )}
          </article>
        ))}
        {!item.evidence.length && <p className="disease-source-empty">No directly readable evidence is available for this item.</p>}
        {item.warnings.map((warning) => <p className="disease-profile-warning" key={warning}>{warning}</p>)}
      </aside>
    </div>
  );
}
