import { AlertTriangle, ExternalLink } from "lucide-react";
import type { LiteratureStudyCard as StudyCard } from "../../../services/api";

interface Props {
  card: StudyCard;
}

function readable(value: string) {
  return value.replaceAll("_", " ");
}

function safePubMedUrl(card: StudyCard) {
  try {
    const url = new URL(card.source_url);
    if (url.protocol !== "https:" || url.hostname !== "pubmed.ncbi.nlm.nih.gov") return null;
    return url.href;
  } catch {
    return null;
  }
}

function warningLabel(warning: string) {
  const labels: Record<string, string> = {
    article_metadata_changed: "PubMed metadata changed after this match was saved.",
    retracted_after_matching: "This article was retracted after it was matched and is no longer shown as evidence.",
    retraction_notice: "PubMed has a retraction notice for this article.",
    expression_of_concern: "PubMed has an expression of concern for this article.",
  };
  return labels[warning] || readable(warning);
}

export default function LiteratureStudyCard({ card }: Props) {
  const sourceUrl = safePubMedUrl(card);
  const warnings = [...new Set(card.warnings)];

  return (
    <article className="literature-study-card">
      {warnings.length > 0 && (
        <div className="literature-card-warnings" role="note">
          <AlertTriangle size={15} />
          <div>
            {warnings.map((warning) => <p key={warning}>{warningLabel(warning)}</p>)}
          </div>
        </div>
      )}

      <div className="literature-card-heading">
        <div>
          <span className="literature-card-kicker">{card.match_specificity === "finding_specific" ? "Finding-specific candidate" : "Condition-only candidate"}</span>
          <h4>{card.title || "Untitled PubMed article"}</h4>
        </div>
        <strong className="literature-score" title="This is a lexical matching score, not an evidence-quality rating.">
          {card.relevance_score}/100
          <small>Match relevance</small>
        </strong>
      </div>

      <div className="literature-card-meta">
        <span>{card.journal || "Journal not reported"}</span>
        {card.publication_year && <span>{card.publication_year}</span>}
        <span>{readable(card.study_category)}</span>
        {card.development_phase !== "not_applicable" && <span>{readable(card.development_phase)}</span>}
      </div>

      {card.publication_types.length > 0 && (
        <div className="literature-card-tags">
          {card.publication_types.slice(0, 5).map((type) => <span key={type}>{type}</span>)}
        </div>
      )}

      {card.matched_terms.length > 0 && (
        <div className="literature-card-terms">
          <span>Matched terms</span>
          <strong>{card.matched_terms.join(" · ")}</strong>
        </div>
      )}

      {card.match_reasons.length > 0 && (
        <div className="literature-card-reasons">
          <span>Why it appears here</span>
          <ul>
            {card.match_reasons.slice(0, 4).map((reason) => <li key={reason}>{reason}</li>)}
          </ul>
        </div>
      )}

      {card.abstract_quote && (
        <blockquote className="literature-abstract-quote">
          <span>Abstract excerpt</span>
          <p>{card.abstract_quote}</p>
        </blockquote>
      )}

      <footer className="literature-card-footer">
        <span>PMID {card.pmid}</span>
        {card.doi && <span>DOI {card.doi}</span>}
        {sourceUrl && (
          <a href={sourceUrl} target="_blank" rel="noopener noreferrer">
            <ExternalLink size={13} />
            View on PubMed
          </a>
        )}
      </footer>
    </article>
  );
}
