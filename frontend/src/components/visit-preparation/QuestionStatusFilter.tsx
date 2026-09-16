import type { ClinicianQuestionStatus } from "../../services/api";

export type QuestionStatusFilterValue = "all" | ClinicianQuestionStatus;

const FILTERS: Array<{ value: QuestionStatusFilterValue; label: string }> = [
  { value: "all", label: "All questions" },
  { value: "saved", label: "Prepare to ask" },
  { value: "asked", label: "Already asked" },
  { value: "answered", label: "Answered" },
  { value: "dismissed", label: "Set aside" },
];

interface Props {
  value: QuestionStatusFilterValue;
  onChange: (value: QuestionStatusFilterValue) => void;
}

export default function QuestionStatusFilter({ value, onChange }: Props) {
  return (
    <div className="visit-filter-row" aria-label="Filter questions">
      {FILTERS.map((filter) => (
        <button
          key={filter.value}
          className={value === filter.value ? "active" : ""}
          type="button"
          aria-pressed={value === filter.value}
          onClick={() => onChange(filter.value)}
        >
          {filter.label}
        </button>
      ))}
    </div>
  );
}
