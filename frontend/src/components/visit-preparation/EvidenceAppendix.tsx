import { FileText } from "lucide-react";
import type { VisitBriefEvidence } from "../../services/api";

interface Props {
  evidence: VisitBriefEvidence[];
  documentTitle?: string;
  printable?: boolean;
}

function locationLabel(item: VisitBriefEvidence, documentTitle?: string) {
  const page = item.page_start
    ? item.page_end && item.page_end !== item.page_start
      ? `Pages ${item.page_start}-${item.page_end}`
      : `Page ${item.page_start}`
    : "Page unavailable";
  const section = item.section_title || item.section_type;
  const location = `${page}${section ? ` · ${section}` : ""}`;
  return documentTitle ? `${documentTitle} · ${location}` : location;
}

export default function EvidenceAppendix({ evidence, documentTitle, printable = false }: Props) {
  if (!evidence.length) return null;

  return (
    <div className="visit-evidence-appendix">
      <span className="visit-eyebrow">Original evidence</span>
      <div className="visit-evidence-list">
        {evidence.map((item) => printable ? (
          <article className="visit-evidence-item visit-evidence-item-printable" key={item.evidence_id}>
            <div className="visit-evidence-summary">
              <FileText size={14} />
              <span>{locationLabel(item, documentTitle)}</span>
            </div>
            <blockquote>{item.quote}</blockquote>
          </article>
        ) : (
          <details className="visit-evidence-item" key={item.evidence_id}>
            <summary>
              <FileText size={14} />
              <span>{locationLabel(item, documentTitle)}</span>
            </summary>
            <blockquote>{item.quote}</blockquote>
          </details>
        ))}
      </div>
    </div>
  );
}
