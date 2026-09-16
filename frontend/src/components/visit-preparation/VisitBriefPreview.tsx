import { CalendarDays, FileText, Printer, Trash2 } from "lucide-react";
import type { VisitBrief } from "../../services/api";
import EvidenceAppendix from "./EvidenceAppendix";

interface Props {
  brief: VisitBrief;
  onPrint: () => void;
  onDelete: () => void | Promise<void>;
  deleting: boolean;
}

function formatDate(value: string) {
  if (!value) return "Unknown date";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

export default function VisitBriefPreview({ brief, onPrint, onDelete, deleting }: Props) {
  return (
    <section className="visit-print-sheet">
      <header className="visit-brief-header">
        <div>
          <span className="visit-eyebrow">Saved snapshot</span>
          <h2>Visit preparation / 就诊准备</h2>
          <p className="visit-brief-meta">
            <CalendarDays size={14} />
            Created {formatDate(brief.generated_at)} · Snapshot created {formatDate(brief.data_cutoff_at)}
          </p>
        </div>
        <div className="visit-brief-actions">
          <button className="visit-secondary-button print-control" type="button" onClick={onPrint}>
            <Printer size={15} />
            Print / Save PDF
          </button>
          <button
            className="visit-icon-button danger print-control"
            type="button"
            onClick={() => void onDelete()}
            disabled={deleting}
            aria-label="Delete visit brief"
            title="Delete visit brief"
          >
            <Trash2 size={15} />
          </button>
        </div>
      </header>

      <p className="visit-brief-disclaimer">{brief.disclaimer}</p>
      <div className="visit-brief-items">
        {brief.items.map((item, index) => (
          <article className="visit-brief-item" key={item.id}>
            <div className="visit-brief-number">{index + 1}</div>
            <div>
              <h3>{item.question}</h3>
              <p>{item.rationale}</p>
              <p className="visit-brief-source">
                <FileText size={13} />
                <span>Source: {item.document_title}</span>
                {item.document_date && <span>· Document date: {item.document_date}</span>}
                {item.parsed_source_hash && (
                  <span>· Source version: {item.parsed_source_hash.slice(0, 12)}</span>
                )}
              </p>
              {item.user_note && (
                <p className="visit-brief-note"><strong>My note:</strong> {item.user_note}</p>
              )}
              <EvidenceAppendix
                evidence={item.evidence}
                documentTitle={item.document_title}
                printable
              />
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
