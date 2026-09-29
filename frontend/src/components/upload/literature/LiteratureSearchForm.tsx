import { useState } from "react";
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
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const selectedFilterCount = form.studyTypes.length
    + (form.dateFrom ? 1 : 0)
    + (form.dateTo ? 1 : 0)
    + (form.sort !== "relevance" ? 1 : 0)
    + (form.maxResults !== 20 ? 1 : 0);

  return (
    <form
      className="literature-search-form"
      noValidate
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

      <details
        className="literature-advanced-filters"
        open={advancedOpen}
        onToggle={(event) => setAdvancedOpen(event.currentTarget.open)}
      >
        <summary>
          <span>Advanced filters</span>
          <span className="literature-filter-count">
            {selectedFilterCount > 0 ? `${selectedFilterCount} selected` : "Optional"}
          </span>
        </summary>
        <div className="literature-advanced-content">
          <div className="literature-form-grid">
            <label className="literature-field">
              <span>From</span>
              <input
                type="date"
                value={form.dateFrom}
                max={form.dateTo || undefined}
                onChange={(event) => onChange("dateFrom", event.target.value)}
                disabled={disabled}
              />
            </label>
            <label className="literature-field">
              <span>To</span>
              <input
                type="date"
                value={form.dateTo}
                min={form.dateFrom || undefined}
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

          <div className="literature-study-types">
            <span className="literature-study-types-label">Study types</span>
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
          </div>
        </div>
      </details>

      <div className="literature-form-footer">
        <span className="literature-form-hint">Only normalized medical terms are sent to PubMed. Your document stays in GraphMind.</span>
        <button className="insight-primary-action literature-search-button" type="submit" disabled={disabled}>
          <Search size={15} />
          Preview PubMed query
        </button>
      </div>
    </form>
  );
}
