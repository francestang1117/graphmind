import { AlertCircle, BookOpen, Loader2, RefreshCw, Search, ShieldCheck } from "lucide-react";
import { useLiteratureEvidence } from "../../../hooks/useLiteratureEvidence";
import LiteratureEvidenceAlerts from "./LiteratureEvidenceAlerts";
import LiteratureFindingGroup from "./LiteratureFindingGroup";
import LiteratureQueryPreview from "./LiteratureQueryPreview";
import LiteratureSearchForm from "./LiteratureSearchForm";

interface Props {
  documentId: string;
  workspaceId?: string | null;
  analysisRunId: string;
  onEvidenceClick?: (evidenceId: string) => void;
}

function readable(value: string) {
  return value.replaceAll("_", " ");
}

export default function LiteratureEvidencePanel({
  documentId,
  workspaceId,
  analysisRunId,
  onEvidenceClick,
}: Props) {
  const literature = useLiteratureEvidence(documentId, workspaceId, analysisRunId);
  const searchRun = literature.searchRun;
  const matchRun = literature.matchRun;
  const searchActive = !literature.draftIsDirty && searchRun && ["queued", "running"].includes(searchRun.status);
  const searchFailed = !literature.draftIsDirty && searchRun?.status === "failed";
  const searchSucceeded = !literature.draftIsDirty && searchRun?.status === "succeeded";
  const staleMetadata = Boolean(
    matchRun?.stale && matchRun.warnings.includes("article_metadata_changed"),
  );

  return (
    <section className="literature-evidence-panel" aria-labelledby="literature-evidence-heading">
      <header className="literature-panel-header">
        <div>
          <span className="section-heading">Evidence matching</span>
          <h3 id="literature-evidence-heading">Find related PubMed literature</h3>
          <p>Compare saved findings with retrieved articles. A match is a retrieval signal, not proof of effectiveness.</p>
        </div>
        <BookOpen size={20} aria-hidden="true" />
      </header>

      <div className="literature-disclosure">
        <ShieldCheck size={17} />
        <div>
          <strong>Before you search</strong>
          <p>Only normalized medical query terms are sent to PubMed. Your document, analysis text, and uploaded file stay on this server.</p>
          <span>The exact query and the local terminology version will be shown before each external search.</span>
        </div>
      </div>

      <LiteratureSearchForm
        form={literature.form}
        onChange={literature.updateForm}
        onToggleStudyType={literature.toggleStudyType}
        onSubmit={literature.previewSearch}
        disabled={literature.previewLoading || literature.startLoading}
      />

      {literature.error && (
        <div className="literature-inline-error" role="alert">
          <AlertCircle size={16} />
          <span>{literature.error}</span>
          <button type="button" onClick={literature.clearError} aria-label="Dismiss literature error">Dismiss</button>
        </div>
      )}

      {literature.preview && (
        <LiteratureQueryPreview
          preview={literature.preview}
          selections={literature.conceptSelections}
          onSelectConcept={literature.selectConcept}
          onRepreview={literature.previewSearch}
          onStart={literature.startSearch}
          previewLoading={literature.previewLoading}
          startLoading={literature.startLoading}
        />
      )}

      {literature.searchError && (
        <div className="literature-inline-error" role="alert">
          <AlertCircle size={16} />
          <span>{literature.searchError}</span>
          <button
            className="literature-secondary-button"
            type="button"
            onClick={literature.retrySearchStatus}
          >
            <RefreshCw size={13} />
            Retry status
          </button>
        </div>
      )}

      {literature.draftIsDirty && searchRun && (
        <div className="literature-draft-warning" role="status">
          <div>
            <strong>Unsaved search changes</strong>
            <p>Saved results are currently hidden and belong to: <span>{searchRun.question}</span></p>
            <button
              className="literature-secondary-button"
              type="button"
              onClick={literature.restoreSavedSearch}
            >
              <RefreshCw size={13} />
              Discard changes and restore saved search
            </button>
          </div>
        </div>
      )}

      {searchActive && (
        <div className="literature-run-status">
          <Loader2 className="spin" size={18} />
          <div>
            <strong>{searchRun.status === "queued" ? "PubMed search queued" : "Searching PubMed"}</strong>
            <p>The search runs in the background. This panel will update automatically.</p>
          </div>
        </div>
      )}

      {searchFailed && (
        <div className="literature-run-status literature-run-status-error">
          <AlertCircle size={18} />
          <div>
            <strong>PubMed search failed</strong>
            <p>{searchRun.error_message || "The search can be retried without changing your document."}</p>
            <button
              className="insight-retry"
              type="button"
              onClick={() => {
                literature.retrySearch();
                literature.previewSearch();
              }}
            >
              <RefreshCw size={14} />
              Review and retry
            </button>
          </div>
        </div>
      )}

      {searchSucceeded && (
        <div className="literature-search-summary">
          <Search size={15} />
          <span>{searchRun.result_count} PubMed article{searchRun.result_count === 1 ? "" : "s"} retrieved</span>
          <span>{readable(searchRun.sort || "relevance")} order</span>
          <span>Search {searchRun.query_hash ? searchRun.query_hash.slice(0, 10) : "n/a"}</span>
        </div>
      )}

      {searchSucceeded && searchRun.warnings.length > 0 && (
        <LiteratureEvidenceAlerts warnings={searchRun.warnings} />
      )}

      {literature.outdatedMatch && (
        <LiteratureEvidenceAlerts warnings={literature.outdatedMatch.warnings} olderAnalysis />
      )}

      {literature.matchLoading && (
        <div className="literature-run-status">
          <Loader2 className="spin" size={18} />
          <div>
            <strong>Comparing findings with PubMed</strong>
            <p>Candidate matching stays local and does not send your document to another service.</p>
          </div>
        </div>
      )}

      {searchSucceeded && !matchRun && !literature.matchLoading && (
        <div className="literature-run-status literature-run-status-neutral">
          <div>
            <strong>Search results are ready</strong>
            <p>Match this search to the current medical analysis to group candidates by finding.</p>
            <button
              className="insight-primary-action"
              type="button"
              onClick={() => literature.matchSearch(searchRun.run_id, true)}
            >
              <Search size={14} />
              Match current analysis
            </button>
          </div>
        </div>
      )}

      {matchRun && !literature.draftIsDirty && (
        <div className="literature-match-results">
          <LiteratureEvidenceAlerts
            warnings={matchRun.warnings.filter((warning) => warning !== "article_metadata_changed")}
            excludedCount={matchRun.summary.retracted_articles_excluded}
            staleMetadata={staleMetadata}
          />
          <div className="literature-match-heading">
            <div>
              <span className="section-heading">Saved local match</span>
              <h3>Findings and candidate literature</h3>
            </div>
            <span className="literature-match-count">{matchRun.match_count} candidate{matchRun.match_count === 1 ? "" : "s"}</span>
          </div>
          {matchRun.findings.length > 0 ? (
            <div className="literature-finding-list">
              {matchRun.findings.map((finding) => (
                <LiteratureFindingGroup
                  finding={finding}
                  key={finding.finding_id}
                  onEvidenceClick={onEvidenceClick}
                />
              ))}
            </div>
          ) : (
            <div className="literature-empty-result">
              <p>No matchable findings were returned for this analysis.</p>
            </div>
          )}
          {matchRun.empty_reason && matchRun.match_count === 0 && (
            <p className="literature-empty-note">No candidate articles remain after the saved safety and retraction checks.</p>
          )}
        </div>
      )}
    </section>
  );
}
