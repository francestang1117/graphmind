import { useEffect, useMemo, useState } from "react";
import axios from "axios";
import { AlertCircle, CheckCircle2, FileSearch, Loader2, RefreshCw, X } from "lucide-react";
import {
  getCurrentMedicalInsights,
  getMedicalInsightConfig,
  getMedicalInsightRun,
  reanalyzeMedicalInsights,
  startMedicalInsights,
  type MedicalInsightEvidence,
  type MedicalInsightFinding,
  type MedicalInsightAttribute,
  type MedicalInsightConfig,
  type MedicalInsightReport,
  type MedicalInsightRun,
} from "../../services/api";

function consentStorageKey(
  config: MedicalInsightConfig,
  documentId: string,
  workspaceId?: string | null,
) {
  return [
    "graphmind.medical-insight-consent.v1",
    workspaceId || "default",
    documentId,
    config.config_fingerprint,
  ].join(":");
}

function savedExternalConsent(
  config: MedicalInsightConfig,
  documentId: string,
  workspaceId?: string | null,
) {
  try {
    return window.localStorage.getItem(
      consentStorageKey(config, documentId, workspaceId),
    ) === "confirmed";
  } catch {
    return false;
  }
}

function saveExternalConsent(
  config: MedicalInsightConfig,
  documentId: string,
  workspaceId?: string | null,
) {
  try {
    window.localStorage.setItem(
      consentStorageKey(config, documentId, workspaceId),
      "confirmed",
    );
  } catch {
    // The explicit confirmation still applies to this open browser session.
  }
}

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

function MethodItem({
  label,
  item,
  evidenceById,
  onSelectEvidence,
}: {
  label: string;
  item: MedicalInsightAttribute;
  evidenceById: Map<string, MedicalInsightEvidence>;
  onSelectEvidence: (evidence: MedicalInsightEvidence) => void;
}) {
  return (
    <div className="insight-method-item">
      <span>{label}</span>
      <strong>{item.value}</strong>
      <span className="insight-type">{readable(item.support_status)}</span>
      {item.evidence_ids.length > 0 && findingEvidence(
        {
          id: `method-${label}`,
          statement: item.value,
          plain_explanation: "",
          evidence_ids: item.evidence_ids,
          evidence_level: "reported_in_document",
          interpretation_type: "direct_statement",
        },
        evidenceById,
        onSelectEvidence,
      )}
    </div>
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

      {report.study_methods && (
        <details className="insight-report-section insight-details">
          <summary>Study methods</summary>
          <div className="insight-method-list">
            <MethodItem label="Design" item={report.study_methods.design} {...{ evidenceById, onSelectEvidence }} />
            <MethodItem label="Population" item={report.study_methods.population} {...{ evidenceById, onSelectEvidence }} />
            <MethodItem label="Evidence subject" item={report.study_methods.human_animal_in_vitro} {...{ evidenceById, onSelectEvidence }} />
            <MethodItem label="Sample size" item={report.study_methods.sample_size} {...{ evidenceById, onSelectEvidence }} />
            <MethodItem label="Comparator" item={report.study_methods.comparator} {...{ evidenceById, onSelectEvidence }} />
          </div>
        </details>
      )}

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
      <FindingList
        title="Where the findings may apply"
        items={report.applicability ?? []}
        evidenceById={evidenceById}
        onSelectEvidence={onSelectEvidence}
      />
      <FindingList
        title="Questions for further research"
        items={report.future_research ?? []}
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

      {report.coverage && (
        <details className="insight-report-section insight-details">
          <summary>Analysis coverage</summary>
          <div className="insight-coverage-grid">
            <span>{report.coverage.selected_chunks} of {report.coverage.total_chunks} source chunks included</span>
            <span>{report.coverage.selected_tokens} of {report.coverage.max_input_tokens} input tokens used</span>
            <span>Included: {report.coverage.included_sections.map(readable).join(", ") || "No labeled sections"}</span>
            {!report.coverage.complete && (
              <span>Not included: {report.coverage.omitted_sections.map(readable).join(", ") || "Some source passages"}</span>
            )}
          </div>
        </details>
      )}
    </div>
  );
}

export default function MedicalInsightPanel({ documentId, title, workspaceId, onClose }: Props) {
  const [run, setRun] = useState<MedicalInsightRun | null>(null);
  const [analysisConfig, setAnalysisConfig] = useState<MedicalInsightConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [configLoading, setConfigLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const [selectedEvidence, setSelectedEvidence] = useState<MedicalInsightEvidence | null>(null);
  const [externalConsent, setExternalConsent] = useState(false);
  const [showExternalConfirmation, setShowExternalConfirmation] = useState(false);
  const [pendingReanalysis, setPendingReanalysis] = useState(false);

  useEffect(() => {
    let active = true;

    getMedicalInsightConfig()
      .then((config) => {
        if (!active) return;
        setAnalysisConfig(config);
        setExternalConsent(
          config.requires_confirmation
          && savedExternalConsent(config, documentId, workspaceId),
        );
      })
      .catch(() => {
        if (active) setError("Could not load the medical analysis configuration.");
      })
      .finally(() => {
        if (active) setConfigLoading(false);
      });

    return () => {
      active = false;
    };
  }, [documentId, workspaceId]);

  useEffect(() => {
    let active = true;

    getCurrentMedicalInsights(documentId, workspaceId)
      .then((result) => {
        if (active) setRun(result);
      })
      .catch((requestError: unknown) => {
        if (!active) return;
        if (!axios.isAxiosError(requestError) || requestError.response?.status !== 404) {
          setError("Could not load the current medical insight.");
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
    let timeoutId: number | undefined;
    let delay = 1000;

    const poll = async () => {
      try {
        const nextRun = await getMedicalInsightRun(runId, workspaceId);
        if (!active) return;
        setRun(nextRun);
        if (nextRun.status !== "queued" && nextRun.status !== "running") return;
      } catch {
        if (!active) return;
        setError("Could not refresh the medical insight status.");
      }

      if (!active) return;
      timeoutId = window.setTimeout(poll, delay);
      delay = delay === 1000 ? 2000 : 5000;
    };

    timeoutId = window.setTimeout(poll, delay);

    return () => {
      active = false;
      if (timeoutId !== undefined) window.clearTimeout(timeoutId);
    };
  }, [run?.run_id, run?.status, workspaceId]);

  const evidenceById = useMemo(
    () => new Map((run?.evidence ?? []).map((evidence) => [evidence.evidence_id, evidence])),
    [run?.evidence],
  );

  const executeAnalysis = async (
    reanalyze: boolean,
    confirmed: boolean,
    configFingerprint?: string,
  ) => {
    setStarting(true);
    setError("");
    setSelectedEvidence(null);
    try {
      const nextRun = reanalyze
        ? await reanalyzeMedicalInsights(
            documentId,
            workspaceId,
            confirmed,
            configFingerprint,
          )
        : await startMedicalInsights(
            documentId,
            workspaceId,
            confirmed,
            configFingerprint,
          );
      setRun(nextRun);
    } catch (requestError) {
      const code = axios.isAxiosError(requestError)
        ? requestError.response?.data?.code
        : undefined;
      if (code === "external_processing_config_changed") {
        try {
          const latestConfig = await getMedicalInsightConfig();
          setAnalysisConfig(latestConfig);
          setExternalConsent(false);
          setPendingReanalysis(reanalyze);
          setShowExternalConfirmation(true);
          setError("External processing settings changed. Review and confirm them again.");
        } catch {
          setError("External processing settings changed, but the new settings could not be loaded.");
        }
      } else {
        setError("Could not start the medical insight. Check that this is a parsed paper or guideline.");
      }
    } finally {
      setStarting(false);
    }
  };

  const runAnalysis = (reanalyze = false) => {
    if (!analysisConfig?.enabled || !analysisConfig.configured) {
      setError("Medical analysis is not configured on the server.");
      return;
    }
    if (analysisConfig.requires_confirmation && !externalConsent) {
      setPendingReanalysis(reanalyze);
      setShowExternalConfirmation(true);
      return;
    }
    void executeAnalysis(
      reanalyze,
      externalConsent,
      analysisConfig.config_fingerprint,
    );
  };

  const confirmExternalAnalysis = () => {
    if (!analysisConfig) return;
    saveExternalConsent(analysisConfig, documentId, workspaceId);
    setExternalConsent(true);
    setShowExternalConfirmation(false);
    void executeAnalysis(
      pendingReanalysis,
      true,
      analysisConfig.config_fingerprint,
    );
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
              disabled={starting || configLoading}
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

      {analysisConfig?.external_processing && (
        <div className="insight-provider-notice insight-provider-notice-before">
          <strong>{readable(analysisConfig.provider)} · {analysisConfig.model_name}</strong>
          <span>
            Analysis sends selected {analysisConfig.redact_pii ? "PII-redacted " : "unredacted "}
            document excerpts to this external provider. API keys remain on the server.
          </span>
          {!analysisConfig.configured && <span>The provider is not fully configured.</span>}
        </div>
      )}

      {showExternalConfirmation && analysisConfig && (
        <div
          className="insight-external-confirmation"
          role="dialog"
          aria-label="Confirm external document processing"
        >
          <strong>Send selected excerpts for analysis?</strong>
          <p>
            {readable(analysisConfig.provider)} will receive selected {analysisConfig.redact_pii ? "PII-redacted" : "unredacted"} passages from this document using {analysisConfig.model_name}.
          </p>
          <div className="insight-confirm-actions">
            <button
              type="button"
              className="insight-retry"
              onClick={() => setShowExternalConfirmation(false)}
            >
              Cancel
            </button>
            <button
              type="button"
              className="insight-primary-action"
              onClick={confirmExternalAnalysis}
            >
              Confirm and analyze
            </button>
          </div>
        </div>
      )}

      {(loading || configLoading) && (
        <div className="parsed-state">
          <Loader2 className="spin" size={18} />
          Loading medical insight...
        </div>
      )}

      {!loading && !configLoading && !run && !error && (
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
            <span><CheckCircle2 size={13} /> Citations and claim wording checked</span>
            <span>{run.provider === "extractive" ? "Local extractive analysis" : `${readable(run.provider)} AI analysis`}</span>
            <span>{run.model_name}</span>
            {run.parsed_source_hash && <span>Source {run.parsed_source_hash.slice(0, 8)}</span>}
            <span>{readable(report.document_kind)}</span>
            <span>{report.language}</span>
            {typeof run.citation_coverage === "number" && (
              <span>{Math.round(run.citation_coverage * 100)}% citation coverage</span>
            )}
          </div>
          {run.provider !== "extractive" && (
            <div className="insight-provider-notice">
              Selected {run.redact_pii ? "redacted " : ""}document excerpts were sent to the configured AI provider.
              {run.redact_pii === false && " PII redaction was disabled for this run."} API keys stay on the server.
            </div>
          )}
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
