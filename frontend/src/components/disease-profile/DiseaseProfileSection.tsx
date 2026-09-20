import { ChevronDown, ChevronRight, FileSearch, TriangleAlert } from "lucide-react";
import type { DiseaseProfileItem, DiseaseProfileSection as SectionName } from "../../services/api";

interface Props {
  name: SectionName;
  count: number;
  items: DiseaseProfileItem[];
  expanded: boolean;
  loading: boolean;
  hasMore: boolean;
  truncated: boolean;
  onToggle: () => void;
  onLoadMore: () => void;
  onOpenSource: (item: DiseaseProfileItem) => void;
}

const LABELS: Record<SectionName, string> = {
  key_findings: "Key findings",
  study_methods: "Study methods",
  limitations: "Limitations",
  what_it_means: "What this means",
  what_it_does_not_mean: "What this does not mean",
  applicability: "Applicability",
  future_research: "Future research",
  medical_terms: "Medical terms",
  clinician_questions: "Questions for a clinician",
  external_studies: "Related external studies",
};

function itemTitle(item: DiseaseProfileItem) {
  if (item.item_type === "article") return item.title || `${item.source.toUpperCase()} ${item.external_id}`;
  if (item.item_type === "question") return item.question;
  if (item.item_type === "term") return item.term;
  if (item.item_type === "attribute") return item.title;
  return item.text;
}

function itemBody(item: DiseaseProfileItem) {
  if (item.item_type === "article") {
    return [
      item.journal,
      item.publication_year ? String(item.publication_year) : "",
      item.publication_types.join(", "),
      item.related_document_count ? `${item.related_document_count} linked documents` : "",
    ].filter(Boolean).join(" · ");
  }
  if (item.item_type === "attribute") return item.value;
  if (item.item_type === "term") return item.explanation;
  return item.explanation || item.rationale;
}

export default function DiseaseProfileSection({
  name,
  count,
  items,
  expanded,
  loading,
  hasMore,
  truncated,
  onToggle,
  onLoadMore,
  onOpenSource,
}: Props) {
  return (
    <section className="disease-profile-section">
      <button type="button" className="disease-profile-section-heading" onClick={onToggle} aria-expanded={expanded}>
        {expanded ? <ChevronDown size={17} /> : <ChevronRight size={17} />}
        <span>{LABELS[name]}</span>
        <strong>{count}</strong>
      </button>
      {expanded && (
        <div className="disease-profile-section-items">
          {loading && <div className="disease-profile-section-loading">Loading sources...</div>}
          {!loading && !items.length && <div className="disease-profile-section-empty">No current items in this section.</div>}
          {items.map((item) => (
            <article className={`disease-profile-item ${item.flagged ? "flagged" : ""}`} key={item.id}>
              <div className="disease-profile-item-topline">
                <span className="disease-profile-item-source">{item.document_title || item.source || "Source"}</span>
                {item.document_date && <span>{item.document_date}</span>}
                {item.flagged && <span className="disease-profile-flag"><TriangleAlert size={13} /> flagged</span>}
              </div>
              <h3>{itemTitle(item)}</h3>
              {itemBody(item) && <p>{itemBody(item)}</p>}
              {item.retraction_status && item.retraction_status !== "unknown" && (
                <p className="disease-profile-warning">Status: {item.retraction_status}</p>
              )}
              {(item.evidence.length || item.evidence_ids.length) > 0 ? (
                <button type="button" className="disease-source-button" onClick={() => onOpenSource(item)}>
                  <FileSearch size={14} />
                  View source ({item.evidence.length || item.evidence_ids.length})
                </button>
              ) : (
                <span className="disease-profile-no-source">
                  {item.warnings.includes("source_unavailable")
                    ? "Source unavailable"
                    : "No source attached"}
                </span>
              )}
            </article>
          ))}
          {truncated && (
            <p className="disease-profile-warning">
              This section is larger than the supported paging window. Showing the available first 10,000 items.
            </p>
          )}
          {hasMore && (
            <button type="button" className="disease-profile-load-more" onClick={onLoadMore} disabled={loading}>
              {loading ? "Loading..." : "Load more"}
            </button>
          )}
        </div>
      )}
    </section>
  );
}
