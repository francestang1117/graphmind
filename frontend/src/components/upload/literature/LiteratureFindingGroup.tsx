import { ArrowRight, FileText } from "lucide-react";
import type { LiteratureFindingMatch } from "../../../services/api";
import LiteratureStudyCard from "./LiteratureStudyCard";

interface Props {
  finding: LiteratureFindingMatch;
  onEvidenceClick?: (evidenceId: string) => void;
}

const STATUS_COPY: Record<string, { label: string; detail: string }> = {
  matched: { label: "Finding-specific matches", detail: "These papers share terms with this finding and the selected condition." },
  condition_only: { label: "Condition-level matches", detail: "These papers share the condition but not enough finding-specific terms." },
  condition_mismatch: { label: "Condition mismatch", detail: "The search results did not share a confirmed condition with this finding." },
  insufficient_terms: { label: "Not enough terms", detail: "There were not enough controlled terms to make a specific comparison." },
  no_candidates: { label: "No candidates", detail: "No usable PubMed candidates remain for this finding." },
};

export default function LiteratureFindingGroup({ finding, onEvidenceClick }: Props) {
  const status = STATUS_COPY[finding.match_status] || {
    label: finding.match_status.replaceAll("_", " "),
    detail: "The matcher returned no additional interpretation.",
  };

  return (
    <article className="literature-finding-group">
      <header className="literature-finding-header">
        <div>
          <span className="literature-card-kicker">{finding.finding_type.replaceAll("_", " ")}</span>
          <h4>{finding.statement}</h4>
        </div>
        <span className={`literature-match-status literature-match-status-${finding.match_status}`}>
          {status.label}
        </span>
      </header>

      {finding.plain_explanation && <p className="literature-finding-explanation">{finding.plain_explanation}</p>}

      {finding.document_evidence_ids.length > 0 && (
        <div className="literature-finding-evidence">
          <FileText size={14} />
          <span>Original analysis evidence</span>
          {finding.document_evidence_ids.map((evidenceId) => (
            <button
              type="button"
              key={evidenceId}
              onClick={() => onEvidenceClick?.(evidenceId)}
              disabled={!onEvidenceClick}
              title={onEvidenceClick ? "Show the source passage" : "Source passage is not available"}
            >
              {evidenceId.slice(0, 10)}
            </button>
          ))}
        </div>
      )}

      <p className="literature-status-detail">{status.detail}</p>

      {finding.candidates.length > 0 && (
        <div className="literature-candidate-cards">
          {finding.candidates.map((candidate) => <LiteratureStudyCard card={candidate} key={candidate.article_id} />)}
        </div>
      )}

      {finding.candidates.length === 0 && (
        <div className="literature-no-candidates">
          <ArrowRight size={14} />
          <span>There is no article card to review for this finding.</span>
        </div>
      )}
    </article>
  );
}
