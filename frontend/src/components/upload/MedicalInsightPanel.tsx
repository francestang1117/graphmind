import { useEffect, useMemo, useState } from "react";
import axios from "axios";
import { AlertCircle, CheckCircle2, FileSearch, Loader2, RefreshCw, X } from "lucide-react";
import {
  getLatestMedicalInsights,
  getMedicalInsightRun,
  reanalyzeMedicalInsights,
  startMedicalInsights,
  type MedicalInsightEvidence,
  type MedicalInsightFinding,
  type MedicalInsightReport,
  type MedicalInsightRun,
} from "../../services/api";

interface Props {
  documentId: string;
  title: string;
  workspaceId?: string | null;
  onClose: () => void;
}

function readable(value: string) {
  return value.replaceAll("_", " ");
}

function locationLabel(evidence: MedicalInsightEvidence) {
  const page = evidence.page_start
    ? evidence.page_end && evidence.page_end !== evidence.page_start
      ? `Pages ${evidence.page_start}-${evidence.page_end}`
      : `Page ${evidence.page_start}`
    : "Page unavailable";
  const section = evidence.section_title || evidence.section_type?.replaceAll("_", " ");
  return `${page}${section ? ` · ${section}` : ""}`;
}

function findingEvidence(
  finding: MedicalInsightFinding,
  evidenceById: Map<string, MedicalInsightEvidence>,
  onSelect: (evidence: MedicalInsightEvidence) => void,
) {
  if (!finding.evidence_ids.length) {
    return <span className="insight-no-evidence">No source attached</span>;
  }

  return (
    <div className="insight-evidence-list">
      {finding.evidence_ids.map((evidenceId) => {
        const evidence = evidenceById.get(evidenceId);
        if (!evidence) return null;
        return (
          <button
            className="insight-evidence-button"
            key={evidenceId}
            type="button"
            onClick={() => onSelect(evidence)}
            title="Show the source passage"
          >
            {locationLabel(evidence)}
          </button>
        );
      })}
    </div>
  );
}

function FindingList({
  title,
  items,
  evidenceById,
  onSelectEvidence,
}: {
  title: string;
  items: MedicalInsightFinding[];
  evidenceById: Map<string, MedicalInsightEvidence>;
  onSelectEvidence: (evidence: MedicalInsightEvidence) => void;
}) {
  if (!items.length) return null;

  return (
    <section className="insight-report-section">
      <h3>{title}</h3>
      <div className="insight-finding-list">
        {items.map((finding) => (
          <article className="insight-finding" key={finding.id}>
            <div className="insight-finding-heading">
              <strong>{finding.statement}</strong>
              <span className="insight-type">{readable(finding.interpretation_type)}</span>
            </div>
            <p>{finding.plain_explanation}</p>
            {findingEvidence(finding, evidenceById, onSelectEvidence)}
          </article>
        ))}
      </div>
    </section>
  );
}

function ReportView({
  report,
  run,
  evidenceById,
  onSelectEvidence,
}: {
  report: MedicalInsightReport;
  run: MedicalInsightRun;
  evidenceById: Map<string, MedicalInsightEvidence>;
  onSelectEvidence: (evidence: MedicalInsightEvidence) => void;
}) {
  return (
    <div className="insight-report">
      <section className="insight-report-section insight-overview">
        <div className="insight-section-heading">
          <h3>Plain-language overview</h3>
          <span className="insight-type">{readable(report.overview.study_type)}</span>
        </div>
        <p>{report.overview.summary}</p>
        {findingEvidence(
          {
            id: "overview",
            statement: report.overview.title,
            plain_explanation: "",
            evidence_ids: report.overview.evidence_ids,
            evidence_level: "reported_in_document",
            interpretation_type: "summary",
          },
          evidenceById,
          onSelectEvidence,
        )}
      </section>

      <FindingList
        title="Key findings"
        items={report.key_findings}
        evidenceById={evidenceById}
        onSelectEvidence={onSelectEvidence}
      />
      <FindingList
        title="What this means"
        items={report.what_it_means}
        evidenceById={evidenceById}
        onSelectEvidence={onSelectEvidence}
      />
      <FindingList
        title="What this does not mean"
        items={report.what_it_does_not_mean}
        evidenceById={evidenceById}
        onSelectEvidence={onSelectEvidence}
      />
      <FindingList
        title="Limitations"
        items={report.limitations}
        evidenceById={evidenceById}
        onSelectEvidence={onSelectEvidence}
      />

      {report.medical_terms.length > 0 && (
        <section className="insight-report-section">
          <h3>Medical terms</h3>
          <div className="insight-term-list">
            {report.medical_terms.map((term) => (
              <article className="insight-term" key={term.term}>
                <strong>{term.term}</strong>
                <p>{term.explanation}</p>
                {findingEvidence(
                  {
                    id: `term-${term.term}`,
                    statement: term.term,
                    plain_explanation: term.explanation,
                    evidence_ids: term.evidence_ids,
                    evidence_level: "reported_in_document",
                    interpretation_type: "summary",
                  },
                  evidenceById,
                  onSelectEvidence,
                )}
              </article>
            ))}
          </div>
        </section>
      )}

      {report.questions_for_professional.length > 0 && (
        <section className="insight-report-section insight-questions">
          <h3>Questions for a professional</h3>
          <ul>
            {report.questions_for_professional.map((question) => (
              <li key={question}>{question}</li>
            ))}
          </ul>
        </section>
      )}

      {run.warnings && run.warnings.length > 0 && (
        <div className="insight-warning">
          <AlertCircle size={16} />
          <div>
            {run.warnings.map((warning) => (
              <p key={warning}>{readable(warning)}</p>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default function MedicalInsightPanel({ documentId, title, workspaceId, onClose }: Props) {
  const [run, setRun] = useState<MedicalInsightRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const [selectedEvidence, setSelectedEvidence] = useState<MedicalInsightEvidence | null>(null);

  useEffect(() => {
    let active = true;

    getLatestMedicalInsights(documentId, workspaceId)
      .then((result) => {
        if (active) setRun(result);
      })
      .catch((requestError: unknown) => {
        if (!active) return;
        if (!axios.isAxiosError(requestError) || requestError.response?.status !== 404) {
          setError("Could not load the latest medical insight.");
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [documentId, workspaceId]);

  useEffect(() => {
    const runId = run?.run_id;
    const runStatus = run?.status;
    if (!runId || (runStatus !== "queued" && runStatus !== "running")) return undefined;

    let active = true;
    const poller = window.setInterval(() => {
      getMedicalInsightRun(runId, workspaceId)
        .then((nextRun) => {
          if (active) setRun(nextRun);
        })
        .catch(() => {
          if (active) setError("Could not refresh the medical insight status.");
        });
    }, 1000);

    return () => {
      active = false;
      window.clearInterval(poller);
    };
  }, [run?.run_id, run?.status, workspaceId]);

  const evidenceById = useMemo(
    () => new Map((run?.evidence ?? []).map((evidence) => [evidence.evidence_id, evidence])),
    [run?.evidence],
  );

  const runAnalysis = async (reanalyze = false) => {
    setStarting(true);
    setError("");
    setSelectedEvidence(null);
    try {
      const nextRun = reanalyze
        ? await reanalyzeMedicalInsights(documentId, workspaceId)
        : await startMedicalInsights(documentId, workspaceId);
      setRun(nextRun);
    } catch {
      setError("Could not start the medical insight. Check that this is a parsed paper or guideline.");
    } finally {
      setStarting(false);
    }
  };

  const report = run?.report;

  return (
    <section className="medical-insight-panel">
      <header className="medical-insight-header">
        <div>
          <span className="section-heading">Medical insight</span>
          <strong>{title}</strong>
        </div>
        <div className="insight-header-actions">
          {run?.status === "succeeded" && (
            <button
              className="row-action"
              type="button"
              onClick={() => runAnalysis(true)}
              disabled={starting}
              aria-label="Re-analyze document"
              title="Re-analyze document"
            >
              {starting ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
            </button>
          )}
          <button className="row-action" type="button" onClick={onClose} aria-label="Close medical insight">
            <X size={17} />
          </button>
        </div>
      </header>

      {loading && (
        <div className="parsed-state">
          <Loader2 className="spin" size={18} />
          Loading medical insight...
        </div>
      )}

      {!loading && !run && !error && (
        <div className="insight-empty">
          <FileSearch size={18} />
          <p>Generate a cited summary for this research paper or guideline.</p>
          <button className="insight-primary-action" type="button" onClick={() => runAnalysis()} disabled={starting}>
            {starting ? <Loader2 className="spin" size={16} /> : <FileSearch size={16} />}
            Analyze document
          </button>
        </div>
      )}

      {error && (
        <div className="parsed-state error">
          <AlertCircle size={17} />
          <span>{error}</span>
          {!run && (
            <button className="insight-retry" type="button" onClick={() => runAnalysis()} disabled={starting}>
              Try again
            </button>
          )}
        </div>
      )}

      {run && ["queued", "running"].includes(run.status) && (
        <div className="insight-status">
          <Loader2 className="spin" size={18} />
          <div>
            <strong>{run.status === "queued" ? "Waiting to analyze" : "Analyzing document"}</strong>
            <p>The original document remains available while this runs.</p>
          </div>
        </div>
      )}

      {run?.status === "failed" && (
        <div className="insight-status error">
          <AlertCircle size={18} />
          <div>
            <strong>Analysis failed</strong>
            <p>{run.error_message || "The source document was not changed."}</p>
            <button className="insight-retry" type="button" onClick={() => runAnalysis(true)} disabled={starting}>
              Try again
            </button>
          </div>
        </div>
      )}

      {run?.status === "succeeded" && report && (
        <>
          <div className="insight-meta">
            <span><CheckCircle2 size={13} /> Validated citations</span>
            <span>{readable(report.document_kind)}</span>
            <span>{report.language}</span>
            {typeof run.citation_coverage === "number" && (
              <span>{Math.round(run.citation_coverage * 100)}% citation coverage</span>
            )}
          </div>
          <ReportView
            report={report}
            run={run}
            evidenceById={evidenceById}
            onSelectEvidence={setSelectedEvidence}
          />
          {selectedEvidence && (
            <aside className="insight-evidence-detail">
              <div>
                <span className="section-heading">Source evidence</span>
                <strong>{locationLabel(selectedEvidence)}</strong>
              </div>
              <button
                className="row-action"
                type="button"
                onClick={() => setSelectedEvidence(null)}
                aria-label="Close source evidence"
              >
                <X size={16} />
              </button>
              <blockquote>{selectedEvidence.quote}</blockquote>
            </aside>
          )}
          <p className="insight-disclaimer">
            AI-generated document explanation only. It is not a diagnosis or treatment recommendation.
          </p>
        </>
      )}
    </section>
  );
}
