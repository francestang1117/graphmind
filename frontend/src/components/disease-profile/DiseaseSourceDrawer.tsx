import { ExternalLink, X } from "lucide-react";
import type { DiseaseProfileItem } from "../../services/api";

interface Props {
  item: DiseaseProfileItem;
  onClose: () => void;
}

export default function DiseaseSourceDrawer({ item, onClose }: Props) {
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
        {item.text && <p className="disease-source-main-text">{item.text}</p>}
        {item.explanation && <p className="disease-source-explanation">{item.explanation}</p>}
        {item.value && <p className="disease-source-main-text"><strong>{item.title}: </strong>{item.value}</p>}
        {item.question && <p className="disease-source-main-text"><strong>{item.question}</strong></p>}
        {item.evidence.map((source) => (
          <article className="disease-source-quote" key={`${source.evidence_id ?? source.external_id}:${source.section_title}`}>
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
