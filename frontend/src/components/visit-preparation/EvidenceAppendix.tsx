import { FileText } from "lucide-react";
import type { VisitBriefEvidence } from "../../services/api";

interface Props {
  evidence: VisitBriefEvidence[];
}

function locationLabel(item: VisitBriefEvidence) {
  const page = item.page_start
    ? item.page_end && item.page_end !== item.page_start
      ? `Pages ${item.page_start}-${item.page_end}`
      : `Page ${item.page_start}`
    : "Page unavailable";
  const section = item.section_title || item.section_type;
  return `${page}${section ? ` · ${section}` : ""}`;
}

export default function EvidenceAppendix({ evidence }: Props) {
  if (!evidence.length) return null;

  return (
    <div className="visit-evidence-appendix">
      <span className="visit-eyebrow">Original evidence</span>
      <div className="visit-evidence-list">
        {evidence.map((item) => (
          <details className="visit-evidence-item" key={item.evidence_id}>
            <summary>
              <FileText size={14} />
              <span>{locationLabel(item)}</span>
            </summary>
            <blockquote>{item.quote}</blockquote>
          </details>
        ))}
      </div>
    </div>
  );
}
