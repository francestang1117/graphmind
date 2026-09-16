import { AlertTriangle, ArrowDown, ArrowUp, FileText, Trash2 } from "lucide-react";
import { useState } from "react";
import type {
  ClinicianQuestion,
  ClinicianQuestionSourceStatus,
  ClinicianQuestionStatus,
} from "../../services/api";
import EvidenceAppendix from "./EvidenceAppendix";

interface UpdateChange {
  status?: ClinicianQuestionStatus;
  priority?: 1 | 2 | 3;
  userNote?: string;
}

interface Props {
  question: ClinicianQuestion;
  selected: boolean;
  selectable: boolean;
  canMoveUp: boolean;
  canMoveDown: boolean;
  onSelect: (selected: boolean) => void;
  onUpdate: (change: UpdateChange) => void | Promise<void>;
  onDelete: () => void | Promise<void>;
  onMoveUp: () => void | Promise<void>;
  onMoveDown: () => void | Promise<void>;
  updating: boolean;
}

const SOURCE_LABELS: Record<ClinicianQuestionSourceStatus, string> = {
  current: "Current source",
  outdated: "Source needs refresh",
  unavailable: "Source unavailable",
};

const STATUS_LABELS: Record<ClinicianQuestionStatus, string> = {
  saved: "Prepare to ask",
  asked: "Already asked",
  answered: "Answered",
  dismissed: "Set aside",
};

function readable(value: string) {
  return value.replaceAll("_", " ");
}

export default function ClinicianQuestionCard({
  question,
  selected,
  selectable,
  canMoveUp,
  canMoveDown,
  onSelect,
  onUpdate,
  onDelete,
  onMoveUp,
  onMoveDown,
  updating,
}: Props) {
  const [note, setNote] = useState(question.user_note);

  const sourceIsCurrent = question.source_status === "current";

  return (
    <article
      className={`visit-question-card ${sourceIsCurrent ? "" : "is-stale"}`}
      aria-busy={updating}
    >
      <div className="visit-question-card-header">
        <label className="visit-question-select">
          <input
            type="checkbox"
            checked={selected}
            disabled={!selectable || updating}
            onChange={(event) => onSelect(event.target.checked)}
            aria-label={`Select question: ${question.question}`}
          />
          <span className="visit-question-priority">P{question.priority}</span>
        </label>
        <span className="visit-question-category">{readable(question.category)}</span>
        <div className="visit-question-actions">
          <button
            className="visit-icon-button"
            type="button"
            onClick={() => void onMoveUp()}
            disabled={!canMoveUp || updating}
            aria-label="Move question up"
            title="Move question up"
          >
            <ArrowUp size={15} />
          </button>
          <button
            className="visit-icon-button"
            type="button"
            onClick={() => void onMoveDown()}
            disabled={!canMoveDown || updating}
            aria-label="Move question down"
            title="Move question down"
          >
            <ArrowDown size={15} />
          </button>
          <button
            className="visit-icon-button danger"
            type="button"
            onClick={() => void onDelete()}
            disabled={updating}
            aria-label="Delete saved question"
            title="Delete saved question"
          >
            <Trash2 size={15} />
          </button>
        </div>
      </div>

      <p className="visit-question-text">{question.question}</p>
      <p className="visit-question-rationale">{question.rationale}</p>

      <div className="visit-question-source">
        <FileText size={14} />
        <span>{question.document_title}</span>
        <span className={`visit-source-status ${question.source_status}`}>
          {question.source_status !== "current" && <AlertTriangle size={13} />}
          {SOURCE_LABELS[question.source_status]}
        </span>
      </div>

      <div className="visit-question-controls">
        <label>
          <span>Status</span>
          <select
            value={question.status}
            disabled={updating}
            onChange={(event) => onUpdate({ status: event.target.value as ClinicianQuestionStatus })}
          >
            {Object.entries(STATUS_LABELS).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </label>
        <label>
          <span>Priority</span>
          <select
            value={question.priority}
            disabled={updating}
            onChange={(event) => onUpdate({ priority: Number(event.target.value) as 1 | 2 | 3 })}
          >
            <option value="1">High</option>
            <option value="2">Medium</option>
            <option value="3">Low</option>
          </select>
        </label>
      </div>

      <label className="visit-question-note">
        <span>Private note</span>
        <textarea
          value={note}
          maxLength={2000}
          placeholder="Add a note for your visit"
          disabled={updating}
          onChange={(event) => setNote(event.target.value)}
          onBlur={() => {
            if (!updating && note !== question.user_note) onUpdate({ userNote: note });
          }}
        />
      </label>

      <EvidenceAppendix evidence={question.evidence} documentTitle={question.document_title} />
    </article>
  );
}
