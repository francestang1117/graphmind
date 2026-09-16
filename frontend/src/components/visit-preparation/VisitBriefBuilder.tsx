import { ClipboardCheck, Loader2 } from "lucide-react";
import type { ClinicianQuestion } from "../../services/api";

interface Props {
  questions: ClinicianQuestion[];
  selectedCount: number;
  includeUserNotes: boolean;
  onIncludeUserNotesChange: (value: boolean) => void;
  onCreate: () => void | Promise<void>;
  creating: boolean;
}

export default function VisitBriefBuilder({
  questions,
  selectedCount,
  includeUserNotes,
  onIncludeUserNotesChange,
  onCreate,
  creating,
}: Props) {
  const canCreate = selectedCount >= 1 && selectedCount <= 10 && questions.length === selectedCount;

  return (
    <section className="visit-prep-builder">
      <div className="visit-section-heading">
        <div>
          <span className="visit-eyebrow">Make a handout</span>
          <h2>Visit preparation</h2>
        </div>
        <ClipboardCheck size={20} />
      </div>
      <p>Select 1 to 10 current questions to create an immutable, printable snapshot.</p>
      <div className="visit-selection-count">
        <strong>{selectedCount}/10</strong>
        <span>selected</span>
      </div>
      <label className="visit-checkbox-row">
        <input
          type="checkbox"
          checked={includeUserNotes}
          onChange={(event) => onIncludeUserNotesChange(event.target.checked)}
        />
        <span>Include my private notes in this snapshot</span>
      </label>
      <button
        className="visit-primary-button"
        type="button"
        disabled={!canCreate || creating}
        onClick={() => void onCreate()}
      >
        {creating ? <Loader2 className="spin" size={15} /> : <ClipboardCheck size={15} />}
        {creating ? "Creating snapshot" : "Create visit brief"}
      </button>
    </section>
  );
}
