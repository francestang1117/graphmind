import { useEffect, useState } from "react";
import { Bookmark, Check, Copy, FileText, Loader2 } from "lucide-react";
import type {
  MedicalInsightEvidence,
  MedicalQuestionSuggestion,
} from "../../../services/api";

const CATEGORY_LABELS: Record<string, string> = {
  clarify_finding: "Helps clarify the finding",
  applicability: "Applicability",
  study_limitation: "Study limitation",
  monitoring_discussion: "Monitoring discussion",
  research_option: "Research direction",
};

interface Props {
  suggestion: MedicalQuestionSuggestion;
  evidenceById: Map<string, MedicalInsightEvidence>;
  onSelectEvidence: (evidence: MedicalInsightEvidence) => void;
  onSave?: () => void;
  saved?: boolean;
  stale?: boolean;
  saving?: boolean;
}

function locationLabel(evidence: MedicalInsightEvidence) {
  const page = evidence.page_start
    ? evidence.page_end && evidence.page_end !== evidence.page_start
      ? `Pages ${evidence.page_start}-${evidence.page_end}`
      : `Page ${evidence.page_start}`
    : "Page unavailable";
  const section = evidence.section_title || evidence.section_type?.replaceAll("_", " ");
  return `${page}${section ? ` · ${section}` : ""}`;
}

export default function QuestionSuggestionCard({
  suggestion,
  evidenceById,
  onSelectEvidence,
  onSave,
  saved = false,
  stale = false,
  saving = false,
}: Props) {
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState(false);

  useEffect(() => {
    if (!copied) return undefined;
    const timer = window.setTimeout(() => setCopied(false), 1800);
    return () => window.clearTimeout(timer);
  }, [copied]);

  async function copyQuestion() {
    const text = [
      "I would like to ask my healthcare professional:",
      suggestion.question,
      "",
      "Why I want to ask:",
      suggestion.rationale,
    ].join("\n");
    try {
      if (!navigator.clipboard?.writeText) throw new Error("clipboard unavailable");
      await navigator.clipboard.writeText(text);
      setCopyError(false);
      setCopied(true);
    } catch {
      setCopied(false);
      setCopyError(true);
    }
  }

  const evidence = suggestion.evidence_ids
    .map((evidenceId) => evidenceById.get(evidenceId))
    .filter((item): item is MedicalInsightEvidence => Boolean(item));

  return (
    <article className="insight-question-item">
      <div className="insight-question-header">
        <span className="insight-question-category">
          {CATEGORY_LABELS[suggestion.category] || "Discussion question"}
        </span>
        <div className="insight-question-actions">
          <button
            className="insight-question-copy"
            type="button"
            onClick={copyQuestion}
            title={copied ? "Question copied" : "Copy this question"}
            aria-label={copied ? "Question copied" : "Copy this question"}
          >
            {copied ? <Check size={14} /> : <Copy size={14} />}
            <span>{copied ? "Copied" : "Copy"}</span>
          </button>
          {onSave && (
            <button
              className="insight-question-save"
              type="button"
              onClick={onSave}
              disabled={saved || saving}
              title={saved ? "Question saved" : stale ? "Refresh saved source" : "Save for visit preparation"}
              aria-label={saved ? "Question saved" : stale ? "Refresh saved source" : "Save question for visit preparation"}
            >
              {saving ? <Loader2 className="spin" size={14} /> : saved ? <Check size={14} /> : <Bookmark size={14} />}
              <span>{saved ? "Saved" : stale ? "Refresh" : "Save"}</span>
            </button>
          )}
        </div>
      </div>
      <h4 className="insight-question-text">{suggestion.question}</h4>
      <p className="insight-question-rationale">{suggestion.rationale}</p>
      {evidence.length > 0 && (
        <div className="insight-question-evidence">
          <span className="insight-question-evidence-label">Source</span>
          {evidence.map((item) => (
            <button
              className="insight-evidence-button"
              key={item.id || item.evidence_id}
              type="button"
              onClick={() => onSelectEvidence(item)}
              title="Show the source passage"
            >
              <FileText size={12} />
              {locationLabel(item)}
            </button>
          ))}
        </div>
      )}
      {copyError && (
        <p className="insight-question-error">
          Could not copy this question. Please select the text manually.
        </p>
      )}
    </article>
  );
}
