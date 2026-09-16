import axios from "axios";
import { AlertCircle, ClipboardList, Loader2, RefreshCw } from "lucide-react";
import { useMemo, useState } from "react";
import { useClinicianQuestions } from "../hooks/useClinicianQuestions";
import { useVisitBriefs } from "../hooks/useVisitBriefs";
import type {
  ClinicianQuestion,
  ClinicianQuestionStatus,
  VisitBrief,
} from "../services/api";
import ClinicianQuestionCard from "./visit-preparation/ClinicianQuestionCard";
import QuestionStatusFilter, {
  type QuestionStatusFilterValue,
} from "./visit-preparation/QuestionStatusFilter";
import VisitBriefBuilder from "./visit-preparation/VisitBriefBuilder";
import VisitBriefPreview from "./visit-preparation/VisitBriefPreview";

interface Props {
  workspaceId: string | null;
}

const GROUPS: Array<{ status: ClinicianQuestionStatus; title: string }> = [
  { status: "saved", title: "Prepare to ask" },
  { status: "asked", title: "Already asked" },
  { status: "answered", title: "Answered" },
  { status: "dismissed", title: "Set aside" },
];

function errorMessage(error: unknown, fallback: string) {
  if (axios.isAxiosError(error)) {
    if (error.response?.status === 409) return "This item changed elsewhere. Refresh the list and try again.";
    if (error.response?.status === 404) return "This item is no longer available in the selected research project.";
    if (error.response?.status === 422) return "That selection is not valid for a visit brief.";
  }
  return fallback;
}

export default function VisitPreparationPanel({ workspaceId }: Props) {
  const questions = useClinicianQuestions(workspaceId);
  const briefs = useVisitBriefs(workspaceId);
  const [filter, setFilter] = useState<QuestionStatusFilterValue>("all");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set());
  const [includeUserNotes, setIncludeUserNotes] = useState(false);
  const [activeBrief, setActiveBrief] = useState<VisitBrief | null>(null);
  const [actionError, setActionError] = useState("");

  const visibleQuestions = useMemo(
    () => questions.items.filter((item) => filter === "all" || item.status === filter),
    [filter, questions.items],
  );
  const selectedQuestions = useMemo(
    () => questions.items
      .filter((item) => selectedIds.has(item.id) && item.status !== "dismissed" && item.source_status === "current")
      .sort((left, right) => left.position - right.position),
    [questions.items, selectedIds],
  );

  const updateQuestion = async (
    item: ClinicianQuestion,
    change: {
      status?: ClinicianQuestionStatus;
      priority?: 1 | 2 | 3;
      userNote?: string;
    },
  ) => {
    setActionError("");
    try {
      await questions.updateQuestion({
        questionId: item.id,
        expected_version: item.version,
        status: change.status,
        priority: change.priority,
        user_note: change.userNote,
      });
    } catch (error) {
      setActionError(errorMessage(error, "Could not update this question."));
    }
  };

  const moveQuestion = async (item: ClinicianQuestion, direction: -1 | 1) => {
    // The server locks and reorders the whole workspace/status group in one
    // transaction, so a failed version check cannot leave a half-swap.
    const ordered = questions.items
      .filter((candidate) => candidate.status === item.status)
      .sort((left, right) => left.position - right.position);
    const index = ordered.findIndex((candidate) => candidate.id === item.id);
    const target = ordered[index + direction];
    if (!target) return;
    setActionError("");
    try {
      await questions.reorderQuestions({
        questionId: item.id,
        targetQuestionId: target.id,
        expectedVersion: item.version,
        targetExpectedVersion: target.version,
      });
    } catch (error) {
      setActionError(errorMessage(error, "Could not reorder this question."));
    }
  };

  const toggleSelected = (item: ClinicianQuestion, selected: boolean) => {
    setActionError("");
    setSelectedIds((current) => {
      const available = new Set(
        questions.items
          .filter((candidate) => candidate.status !== "dismissed" && candidate.source_status === "current")
          .map((candidate) => candidate.id),
      );
      const next = new Set([...current].filter((id) => available.has(id)));
      if (selected) {
        if (next.size >= 10) {
          setActionError("A visit brief can contain at most 10 questions.");
          return current;
        }
        next.add(item.id);
      } else {
        next.delete(item.id);
      }
      return next;
    });
  };

  const createBrief = async () => {
    setActionError("");
    try {
      const brief = await briefs.createBrief({
        questionIds: selectedQuestions.map((item) => item.id),
        includeUserNotes,
      });
      setActiveBrief(brief);
    } catch (error) {
      setActionError(errorMessage(error, "Could not create the visit preparation snapshot."));
    }
  };

  const deleteBrief = async (brief: VisitBrief) => {
    setActionError("");
    try {
      await briefs.deleteBrief(brief.id);
      setActiveBrief((current) => current?.id === brief.id ? null : current);
    } catch (error) {
      setActionError(errorMessage(error, "Could not delete this visit brief."));
    }
  };

  if (!workspaceId) {
    return (
      <div className="visit-preparation-panel visit-empty-state">
        <ClipboardList size={30} />
        <h2>Select a research project</h2>
        <p>Saved clinician questions are kept inside their research project.</p>
      </div>
    );
  }

  const loadError = questions.error || briefs.error;
  const displayedBrief = activeBrief;

  return (
    <div className="visit-preparation-panel">
      <header className="visit-prep-header">
        <div>
          <span className="visit-eyebrow">Research project workspace</span>
          <h1>Visit preparation</h1>
          <p>Keep evidence-backed questions together for a focused conversation with a healthcare professional.</p>
        </div>
        <ClipboardList size={28} aria-hidden="true" />
      </header>

      <div className="visit-safety-notice">
        <AlertCircle size={17} />
        <span>Questions are generated from validated document analysis. They are for discussion with a healthcare professional, not diagnosis or treatment instructions.</span>
      </div>

      {loadError && (
        <div className="visit-inline-error" role="alert">
          <AlertCircle size={16} />
          <span>Could not load visit preparation data.</span>
          <button type="button" onClick={() => { void questions.refetch(); void briefs.refetch(); }}>
            <RefreshCw size={14} />
            Retry
          </button>
        </div>
      )}

      {actionError && (
        <div className="visit-inline-error" role="alert">
          <AlertCircle size={16} />
          <span>{actionError}</span>
        </div>
      )}

      <div className="visit-prep-layout">
        <main className="visit-question-column">
          <div className="visit-toolbar">
            <div>
              <span className="visit-eyebrow">Saved questions</span>
              <strong>{questions.total} total</strong>
            </div>
            <QuestionStatusFilter value={filter} onChange={setFilter} />
          </div>

          {questions.isLoading ? (
            <div className="visit-loading"><Loader2 className="spin" size={20} /> Loading saved questions...</div>
          ) : visibleQuestions.length === 0 ? (
            <div className="visit-empty-state compact">
              <ClipboardList size={24} />
              <strong>No questions here yet</strong>
              <p>Save a question from a completed medical analysis to add it to this list.</p>
            </div>
          ) : (
            <div className="visit-question-groups">
              {GROUPS
                .filter((group) => filter === "all" || filter === group.status)
                .map((group) => {
                  const groupItems = visibleQuestions.filter((item) => item.status === group.status);
                  if (!groupItems.length) return null;
                  return (
                    <section className="visit-question-group" key={group.status}>
                      <div className="visit-group-heading">
                        <h2>{group.title}</h2>
                        <span>{groupItems.length}</span>
                      </div>
                      {groupItems.map((item) => {
                        const orderedGroup = [...groupItems].sort((left, right) => left.position - right.position);
                        const groupIndex = orderedGroup.findIndex((candidate) => candidate.id === item.id);
                        return (
                          <ClinicianQuestionCard
                            key={`${item.id}:${item.version}`}
                            question={item}
                            selected={selectedIds.has(item.id)}
                            selectable={item.status !== "dismissed" && item.source_status === "current"}
                            updating={questions.updating}
                            canMoveUp={groupIndex > 0}
                            canMoveDown={groupIndex < orderedGroup.length - 1}
                            onSelect={(selected) => toggleSelected(item, selected)}
                            onUpdate={(change) => updateQuestion(item, change)}
                            onDelete={async () => {
                              try {
                                await questions.deleteQuestion(item.id);
                              } catch (error) {
                                setActionError(errorMessage(error, "Could not delete this question."));
                              }
                            }}
                            onMoveUp={() => moveQuestion(item, -1)}
                            onMoveDown={() => moveQuestion(item, 1)}
                          />
                        );
                      })}
                    </section>
                  );
                })}
            </div>
          )}
        </main>

        <aside className="visit-prep-sidebar">
          <VisitBriefBuilder
            questions={selectedQuestions}
            selectedCount={selectedQuestions.length}
            includeUserNotes={includeUserNotes}
            onIncludeUserNotesChange={setIncludeUserNotes}
            onCreate={createBrief}
            creating={briefs.creating}
          />

          {displayedBrief ? (
            <VisitBriefPreview
              brief={displayedBrief}
              onPrint={() => window.print()}
              onDelete={() => deleteBrief(displayedBrief)}
              deleting={briefs.deleting}
            />
          ) : briefs.briefs.length > 0 ? (
            <section className="visit-saved-briefs">
              <div className="visit-section-heading"><h2>Saved visit briefs</h2></div>
              {briefs.briefs.map((brief) => (
                <button type="button" key={brief.id} onClick={() => setActiveBrief(brief)}>
                  {new Date(brief.generated_at).toLocaleString()} · {brief.items.length} questions
                </button>
              ))}
            </section>
          ) : null}
        </aside>
      </div>
    </div>
  );
}
