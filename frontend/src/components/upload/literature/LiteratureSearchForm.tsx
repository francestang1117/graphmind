import { Search } from "lucide-react";
import {
  LITERATURE_STUDY_TYPES,
  type LiteratureFormState,
} from "../../../hooks/useLiteratureEvidence";

interface Props {
  form: LiteratureFormState;
  onChange: (field: keyof LiteratureFormState, value: string | number) => void;
  onToggleStudyType: (studyType: string) => void;
  onSubmit: () => void;
  disabled?: boolean;
}

export default function LiteratureSearchForm({
  form,
  onChange,
  onToggleStudyType,
  onSubmit,
  disabled = false,
}: Props) {
  return (
    <form
      className="literature-search-form"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <label className="literature-field literature-field-wide">
        <span>Research question</span>
        <textarea
          value={form.question}
          onChange={(event) => onChange("question", event.target.value)}
          placeholder="What evidence should we look for?"
          rows={3}
          maxLength={500}
          disabled={disabled}
        />
      </label>

      <div className="literature-form-grid">
        <label className="literature-field">
          <span>From</span>
          <input
            type="date"
            value={form.dateFrom}
            onChange={(event) => onChange("dateFrom", event.target.value)}
            disabled={disabled}
          />
        </label>
        <label className="literature-field">
          <span>To</span>
          <input
            type="date"
            value={form.dateTo}
            onChange={(event) => onChange("dateTo", event.target.value)}
            disabled={disabled}
          />
        </label>
        <label className="literature-field">
          <span>Sort</span>
          <select
            value={form.sort}
            onChange={(event) => onChange("sort", event.target.value === "newest" ? "newest" : "relevance")}
            disabled={disabled}
          >
            <option value="relevance">Relevance</option>
            <option value="newest">Newest first</option>
          </select>
        </label>
        <label className="literature-field">
          <span>Max results</span>
          <input
            type="number"
            min={1}
            max={50}
            value={form.maxResults}
            onChange={(event) => onChange("maxResults", Math.min(50, Math.max(1, Number(event.target.value) || 1)))}
            disabled={disabled}
          />
        </label>
      </div>

      <fieldset className="literature-study-types">
        <legend>Study types</legend>
        <div className="literature-checkbox-grid">
          {LITERATURE_STUDY_TYPES.map((studyType) => (
            <label className="literature-checkbox" key={studyType.value}>
              <input
                type="checkbox"
                checked={form.studyTypes.includes(studyType.value)}
                onChange={() => onToggleStudyType(studyType.value)}
                disabled={disabled}
              />
              <span>{studyType.label}</span>
            </label>
          ))}
        </div>
      </fieldset>

      <div className="literature-form-footer">
        <span className="literature-form-hint">The document itself is not sent to PubMed.</span>
        <button className="insight-primary-action literature-search-button" type="submit" disabled={disabled}>
          <Search size={15} />
          Preview PubMed query
        </button>
      </div>
    </form>
  );
}
