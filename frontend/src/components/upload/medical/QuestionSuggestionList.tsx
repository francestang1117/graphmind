import type {
  MedicalInsightEvidence,
  MedicalInsightReport,
  MedicalQuestionSuggestion,
} from "../../../services/api";
import QuestionSuggestionCard from "./QuestionSuggestionCard";

interface Props {
  report: MedicalInsightReport;
  evidenceById: Map<string, MedicalInsightEvidence>;
  onSelectEvidence: (evidence: MedicalInsightEvidence) => void;
  onSaveSuggestion?: (suggestion: MedicalQuestionSuggestion) => void;
  savedSuggestionIds?: ReadonlySet<string>;
  staleSuggestionIds?: ReadonlySet<string>;
  savingSuggestionId?: string | null;
}

export default function QuestionSuggestionList({
  report,
  evidenceById,
  onSelectEvidence,
  onSaveSuggestion,
  savedSuggestionIds,
  staleSuggestionIds,
  savingSuggestionId,
}: Props) {
  const suggestions = (report.question_suggestions ?? []).slice(0, 5);
  const legacyQuestions = report.schema_version === "medical-insights-v2"
    ? report.questions_for_professional ?? []
    : [];
  if (!suggestions.length && !legacyQuestions.length) return null;

  return (
    <section className="insight-report-section insight-question-list">
      <div className="insight-section-heading">
        <h3>Questions to discuss with a healthcare professional</h3>
      </div>
      <p className="insight-question-safety">
        These questions help you discuss the document with a healthcare professional. They are not a diagnosis, test, or treatment recommendation.
      </p>
      {suggestions.length > 0 ? (
        <div className="insight-question-grid">
          {suggestions.map((suggestion) => (
            <QuestionSuggestionCard
              key={suggestion.id}
              suggestion={suggestion}
              evidenceById={evidenceById}
              onSelectEvidence={onSelectEvidence}
              onSave={onSaveSuggestion ? () => onSaveSuggestion(suggestion) : undefined}
              saved={savedSuggestionIds?.has(suggestion.id) ?? false}
              stale={staleSuggestionIds?.has(suggestion.id) ?? false}
              saving={savingSuggestionId === suggestion.id}
            />
          ))}
        </div>
      ) : (
        <ul className="insight-questions-legacy">
          {legacyQuestions.map((question) => <li key={question}>{question}</li>)}
        </ul>
      )}
    </section>
  );
}
