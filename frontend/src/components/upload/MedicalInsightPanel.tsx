import { useCallback, useEffect, useMemo, useState } from "react";
import axios from "axios";
import { AlertCircle, FileSearch, Loader2, RefreshCw, X } from "lucide-react";
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
import LiteratureEvidencePanel from "./literature/LiteratureEvidencePanel";
import QuestionSuggestionList from "./medical/QuestionSuggestionList";
import { useClinicianQuestions } from "../../hooks/useClinicianQuestions";
import {
  ApplicationUpdateIncompleteError,
  frontendRuntimeCommit,
  type MedicalRuntimeVersions,
} from "../../services/runtimeVersion";

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

function isApplicationVersionError(
  error: unknown,
): error is ApplicationUpdateIncompleteError {
  return error instanceof ApplicationUpdateIncompleteError;
}

function warningLabel(warning: string) {
  switch (warning) {
    case "not_medical_advice":
      return "For research support only; this is not medical advice.";
    case "pii_redacted":
      return "Sensitive personal information was removed before analysis.";
    case "extractive_output":
      return "This report is a source extract, not a generated plain-language explanation.";
    case "pdf_layout_reconstructed":
    case "pdf_text_degraded":
      return "Some PDF text was reconstructed from its word layout; check the cited passage in the original document.";
    case "pdf_text_reconstructed":
      return "Some PDF text was reconstructed from its word layout.";
    case "analysis_report_unavailable":
      return "The analysis report is unavailable and cannot be used as evidence.";
    case "no_reliable_key_findings":
      return "No reliable key findings could be extracted from this document.";
    case "evidence_quality_filtered":
      return "Some source passages were excluded because they were not suitable for the evidence context.";
    case "study_aim_unavailable":
      return "The study aim was not clearly identified in the analyzed text; the overview is shown as background.";
    case "pdf_layout_ambiguous":
      return "The PDF column layout could not be read reliably; analysis was stopped for safety.";
    case "table_location_unavailable":
      return "A table was found, but its exact source location could not be confirmed.";
    case "figure_location_unavailable":
      return "A figure was found, but its exact source location could not be confirmed.";
    default:
      return readable(warning);
  }
}

function visibleProcessingWarnings(warnings: string[] | undefined) {
  const normalized = (warnings ?? []).map((warning) => (
    warning === "pdf_text_degraded" || warning === "pdf_text_reconstructed"
      ? "pdf_layout_reconstructed"
      : warning
  ));
  return [...new Set(normalized)].filter(
    (warning) => ![
      "not_medical_advice",
      "extractive_output",
      "pii_redacted",
      // This explanation is already shown next to the Background heading.
      "study_aim_unavailable",
    ].includes(warning),
  );
}

function locationLabel(evidence: MedicalInsightEvidence) {
  const page = evidence.page_start
    ? evidence.page_end && evidence.page_end !== evidence.page_start
      ? `Pages ${evidence.page_start}-${evidence.page_end}`
      : `Page ${evidence.page_start}`
    : "Page unavailable";
  const rawSectionType = evidence.section_type?.replaceAll("_", " ").trim();
  const sectionType = rawSectionType && rawSectionType !== "unknown"
    ? `${rawSectionType.slice(0, 1).toUpperCase()}${rawSectionType.slice(1)}`
    : "";
  const section = sectionType || evidence.section_title;
  return `${page}${section ? ` · ${section}` : ""}`;
}

function passageExcerpt(evidence: MedicalInsightEvidence) {
  const sourceText = evidence.excerpt?.trim() || evidence.quote;
  const sentences = sourceText
    .split(/(?<=[.!?。！？])\s+/)
    .map((part) => part.trim())
    .filter(Boolean);
  return sentences[0] || sourceText;
}

function sampleSizeRows(label: string, value: string) {
  if (label !== "Sample size") return null;
  const rows = value
    .split(/;\s+(?=(?:Plasma|Urine):)/i)
    .map((part) => {
      const match = part.match(/^(Plasma|Urine):\s*(.*)$/i);
      return match ? [match[1], match[2]] as const : null;
    })
    .filter((row): row is readonly [string, string] => Boolean(row));
  return rows.length > 1 ? rows : null;
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
            </div>
            {finding.interpretation_type !== "direct_statement" && finding.plain_explanation && (
              <p>{finding.plain_explanation}</p>
            )}
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
  const cohortRows = sampleSizeRows(label, item.value);
  return (
    <div className="insight-method-item">
      <span>{label}</span>
      {cohortRows ? (
        <div className="insight-method-rows">
          {cohortRows.map(([cohort, value]) => (
            <div key={cohort}>
              <span>{cohort}</span>
              <strong>{value}</strong>
            </div>
          ))}
        </div>
      ) : <strong>{item.value}</strong>}
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
  onSaveSuggestion,
  savedSuggestionIds,
  staleSuggestionIds,
  savingSuggestionId,
}: {
  report: MedicalInsightReport;
  run: MedicalInsightRun;
  evidenceById: Map<string, MedicalInsightEvidence>;
  onSelectEvidence: (evidence: MedicalInsightEvidence) => void;
  onSaveSuggestion?: (suggestion: NonNullable<MedicalInsightReport["question_suggestions"]>[number]) => void;
  savedSuggestionIds?: ReadonlySet<string>;
  staleSuggestionIds?: ReadonlySet<string>;
  savingSuggestionId?: string | null;
}) {
  const isExtractive =
    run.provider === "extractive"
    || report.warnings.includes("extractive_output");
  const methodFields = [
    ["Study design", report.study_methods?.design],
    ["Population", report.study_methods?.population],
    [
      "What was measured",
      report.study_methods?.what_was_measured
        ?? report.study_methods?.human_animal_in_vitro,
    ],
    ["Sample size", report.study_methods?.sample_size],
    ["Comparator", report.study_methods?.comparator],
  ] as const;
  const availableMethods = methodFields.filter(([, item]) =>
    Boolean(item?.value?.trim()) && item?.support_status !== "not_reported",
  );
  const unavailableMethods = methodFields.filter(([, item]) =>
    !item?.value?.trim() || item?.support_status === "not_reported",
  );
  const sourcePassages = [...evidenceById.values()];
  const processingWarnings = visibleProcessingWarnings(run.warnings);
  const hasAdditionalAnalysis = Boolean(
    report.limitations.length
    || report.what_it_means.length
    || report.what_it_does_not_mean.length
    || report.applicability?.length
    || report.future_research?.length
    || report.medical_terms.length,
  );
  return (
    <div className="insight-report">
      <section className="insight-report-section insight-overview">
        <h3>{report.warnings.includes("study_aim_unavailable") ? "Background" : "About this paper"}</h3>
        <p className="insight-readable-content">{report.overview.summary}</p>
        {report.warnings.includes("study_aim_unavailable") && (
          <p className="insight-muted-note">Study aim was not clearly identified in the analyzed text.</p>
        )}
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
        title="Reported results"
        items={report.key_findings}
        evidenceById={evidenceById}
        onSelectEvidence={onSelectEvidence}
      />
      {!report.key_findings.length && report.warnings.includes("no_reliable_key_findings") && (
        <section className="insight-report-section insight-empty-findings" role="status">
          <h3>Reported results</h3>
          <p>No reliable reported results could be extracted from this document.</p>
        </section>
      )}

      <FindingList
        title="Authors’ conclusions"
        items={report.authors_conclusions ?? []}
        evidenceById={evidenceById}
        onSelectEvidence={onSelectEvidence}
      />

      <QuestionSuggestionList
        report={report}
        evidenceById={evidenceById}
        onSelectEvidence={onSelectEvidence}
        onSaveSuggestion={onSaveSuggestion}
        savedSuggestionIds={savedSuggestionIds}
        staleSuggestionIds={staleSuggestionIds}
        savingSuggestionId={savingSuggestionId}
      />

      {report.study_methods && (
        <details className="insight-report-section insight-details">
          <summary>
            Study details
            {unavailableMethods.length > 0 && (
              <span className="insight-summary-count">
                {availableMethods.length} fields identified · {unavailableMethods.length} not identified
              </span>
            )}
          </summary>
          <div className="insight-method-list">
            {availableMethods.map(([label, item]) => item && (
              <MethodItem key={label} label={label} item={item} {...{ evidenceById, onSelectEvidence }} />
            ))}
          </div>
          {availableMethods.length === 0 && (
            <p className="insight-muted-note">No study details were identified in the analyzed text.</p>
          )}
          {unavailableMethods.length > 0 && (
            <details className="insight-unavailable-methods">
              <summary>View unavailable fields</summary>
              <ul>
                {unavailableMethods.map(([label]) => <li key={label}>{label} · Not found in analyzed text</li>)}
              </ul>
            </details>
          )}
        </details>
      )}

      {sourcePassages.length > 0 && (
        <details className="insight-report-section insight-details">
          <summary>Source passages <span className="insight-summary-count">{sourcePassages.length}</span></summary>
          <ol className="insight-source-passages">
            {sourcePassages.map((evidence) => (
              <li key={evidence.evidence_id}>
                <button type="button" className="insight-source-link" onClick={() => onSelectEvidence(evidence)}>
                  {locationLabel(evidence)}
                </button>
                <p>{passageExcerpt(evidence)}</p>
                {passageExcerpt(evidence) !== evidence.quote && (
                  <details className="insight-full-passage">
                    <summary>View full passage</summary>
                    <p>{evidence.quote}</p>
                  </details>
                )}
              </li>
            ))}
          </ol>
        </details>
      )}

      {report.coverage && (
        <details className="insight-report-section insight-details">
          <summary>Analysis coverage</summary>
          <div className="insight-coverage-grid">
            <span>
              {report.coverage.selected_chunks} of {(report.coverage.eligible_chunks ?? report.coverage.total_chunks)} eligible source chunks included
            </span>
            {Boolean(report.coverage.source_chunks_total) && (
              <span>{report.coverage.source_chunks_total} source chunks scanned before quality and scope filtering</span>
            )}
            {Boolean(report.coverage.quality_filtered_chunks) && (
              <span>{report.coverage.quality_filtered_chunks} source chunks excluded for text quality</span>
            )}
            {Boolean(report.coverage.scope_excluded_chunks) && (
              <span>{report.coverage.scope_excluded_chunks} source chunks excluded by evidence scope</span>
            )}
            {Boolean(report.coverage.duplicate_chunks) && (
              <span>{report.coverage.duplicate_chunks} duplicate source chunks removed</span>
            )}
            {Boolean(report.coverage.budget_excluded_chunks) && (
              <span>{report.coverage.budget_excluded_chunks} eligible chunks not included because of the context limit</span>
            )}
            <span>
              Approximately {report.coverage.selected_tokens.toLocaleString()} source tokens selected; limit {report.coverage.max_input_tokens.toLocaleString()}
            </span>
            <span>Included: {report.coverage.included_sections.map(readable).join(", ") || "No labeled sections"}</span>
            {!report.coverage.complete && (
              <span>Not included: {report.coverage.omitted_sections.map(readable).join(", ") || "Some source passages"}</span>
            )}
          </div>
        </details>
      )}

      {hasAdditionalAnalysis && (
        <details className="insight-report-section insight-details">
          <summary>Additional analysis</summary>
          {!isExtractive && (
            <>
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
            </>
          )}
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
        </details>
      )}

      {processingWarnings.length > 0 && (
        <details className="insight-report-section insight-details">
          <summary>Processing notes</summary>
          <ul className="insight-processing-notes">
            {processingWarnings.map((warning) => <li key={warning}>{warningLabel(warning)}</li>)}
          </ul>
        </details>
      )}
    </div>
  );
}

export default function MedicalInsightPanel({ documentId, title, workspaceId, onClose }: Props) {
  const contextKey = `${workspaceId || "default"}:${documentId}`;
  const [runState, setRunState] = useState<{
    contextKey: string;
    value: MedicalInsightRun | null;
  }>({ contextKey: "", value: null });
  const [runtimeErrorState, setRuntimeErrorState] = useState<{
    contextKey: string;
    versions: MedicalRuntimeVersions;
  } | null>(null);
  const applicationUpdateIncomplete = runtimeErrorState?.contextKey === contextKey;
  const run = !applicationUpdateIncomplete && runState.contextKey === contextKey
    ? runState.value
    : null;
  const setCurrentRun = useCallback(
    (value: MedicalInsightRun | null) => setRunState({ contextKey, value }),
    [contextKey],
  );
  const [analysisConfig, setAnalysisConfig] = useState<MedicalInsightConfig | null>(null);
  const [loadedContextKey, setLoadedContextKey] = useState("");
  const loading = loadedContextKey !== contextKey;
  const [configLoading, setConfigLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [errorState, setErrorState] = useState({ contextKey: "", value: "" });
  const error = errorState.contextKey === contextKey ? errorState.value : "";
  const setError = useCallback(
    (value: string) => setErrorState({ contextKey, value }),
    [contextKey],
  );
  const [outdatedContextKey, setOutdatedContextKey] = useState("");
  const analysisOutdated = outdatedContextKey === contextKey;
  const outdatedNeedsConfirmation = Boolean(
    analysisOutdated
      && analysisConfig?.enabled
      && analysisConfig.configured
      && analysisConfig.requires_confirmation,
  );
  const [selectedEvidence, setSelectedEvidence] = useState<MedicalInsightEvidence | null>(null);
  const [externalConsent, setExternalConsent] = useState(false);
  const [showExternalConfirmation, setShowExternalConfirmation] = useState(false);
  const [pendingReanalysis, setPendingReanalysis] = useState(false);
  const clinicianQuestions = useClinicianQuestions(workspaceId, documentId);

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
      .catch((requestError: unknown) => {
        if (!active) return;
        if (isApplicationVersionError(requestError)) {
          setRuntimeErrorState({ contextKey, versions: requestError.versions });
          setCurrentRun(null);
          setError("");
          return;
        }
        setError("Could not load the medical analysis configuration.");
      })
      .finally(() => {
        if (active) setConfigLoading(false);
      });

    return () => {
      active = false;
    };
  }, [contextKey, documentId, setCurrentRun, setError, workspaceId]);

  useEffect(() => {
    let active = true;
    getCurrentMedicalInsights(documentId, workspaceId)
      .then((result) => {
        if (!active) return;
        if (result.status === "succeeded" && (result.outdated || result.is_current === false)) {
          setCurrentRun(null);
          setSelectedEvidence(null);
          setError("");
          setOutdatedContextKey(contextKey);
          return;
        }
        setCurrentRun(result);
      })
      .catch((requestError: unknown) => {
        if (!active) return;
        if (isApplicationVersionError(requestError)) {
          setRuntimeErrorState({ contextKey, versions: requestError.versions });
          setCurrentRun(null);
          setSelectedEvidence(null);
          setError("");
          return;
        }
        const code = axios.isAxiosError(requestError)
          ? requestError.response?.data?.code
          : undefined;
        if (code === "analysis_outdated") {
          setCurrentRun(null);
          setSelectedEvidence(null);
          setError("");
          setOutdatedContextKey(contextKey);
          return;
        }
        if (!axios.isAxiosError(requestError) || requestError.response?.status !== 404) {
          setError("Could not load the current medical insight.");
        }
      })
      .finally(() => {
        if (active) setLoadedContextKey(contextKey);
      });

    return () => {
      active = false;
    };
  }, [contextKey, documentId, setCurrentRun, setError, workspaceId]);

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
        if (nextRun.outdated || nextRun.is_current === false) {
          setCurrentRun(null);
          setSelectedEvidence(null);
          setOutdatedContextKey(contextKey);
          setError("");
          return;
        }
        setCurrentRun(nextRun);
        if (nextRun.status !== "queued" && nextRun.status !== "running") return;
      } catch (requestError: unknown) {
        if (!active) return;
        if (isApplicationVersionError(requestError)) {
          setRuntimeErrorState({ contextKey, versions: requestError.versions });
          setCurrentRun(null);
          setSelectedEvidence(null);
          setError("");
          return;
        }
        const code = axios.isAxiosError(requestError)
          ? requestError.response?.data?.code
          : undefined;
        if (code === "analysis_outdated") {
          setCurrentRun(null);
          setSelectedEvidence(null);
          setOutdatedContextKey(contextKey);
          setError("");
          return;
        }
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
  }, [contextKey, run?.run_id, run?.status, setCurrentRun, setError, workspaceId]);

  const evidenceById = useMemo(
    () => new Map((run?.evidence ?? []).map((evidence) => [evidence.evidence_id, evidence])),
    [run?.evidence],
  );

  const executeAnalysis = useCallback(async (
    reanalyze: boolean,
    confirmed: boolean,
    configFingerprint?: string,
  ) => {
    setOutdatedContextKey("");
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
      setCurrentRun(nextRun);
    } catch (requestError) {
      if (isApplicationVersionError(requestError)) {
        setRuntimeErrorState({ contextKey, versions: requestError.versions });
        setCurrentRun(null);
        setError("");
        return;
      }
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
  }, [contextKey, documentId, setCurrentRun, setError, workspaceId]);

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
      analysisOutdated || pendingReanalysis,
      true,
      analysisConfig.config_fingerprint,
    );
  };

  useEffect(() => {
    if (!analysisOutdated || loading || configLoading || !analysisConfig || starting) return;

    if (!analysisConfig.enabled || !analysisConfig.configured) {
      return;
    }
    if (analysisConfig.requires_confirmation) {
      return;
    }

    const timeoutId = window.setTimeout(() => {
      void executeAnalysis(false, false, analysisConfig.config_fingerprint);
    }, 0);
    return () => window.clearTimeout(timeoutId);
  }, [analysisConfig, analysisOutdated, configLoading, executeAnalysis, loading, starting]);

  const report = run?.report;
  if (applicationUpdateIncomplete && runtimeErrorState) {
    const versions = runtimeErrorState.versions;
    return (
      <section className="medical-insight-panel">
        <header className="medical-insight-header">
          <div>
            <span className="section-heading">Medical insight</span>
            <strong>{title}</strong>
          </div>
          <button className="row-action" type="button" onClick={onClose} aria-label="Close medical insight">
            <X size={17} />
          </button>
        </header>
        <div className="insight-version-mismatch" role="alert">
          <AlertCircle size={19} />
          <div>
            <strong>Application update incomplete</strong>
            <p>The frontend and backend versions do not match. This report is hidden to prevent showing stale analysis.</p>
            <dl>
              <div><dt>Frontend</dt><dd>{frontendRuntimeCommit()}</dd></div>
              <div><dt>Backend</dt><dd>{versions.backendCommit}</dd></div>
              <div><dt>PDF parser</dt><dd>{versions.parserVersion}</dd></div>
              <div><dt>Analysis pipeline</dt><dd>{versions.analysisPipelineVersion}</dd></div>
              <div><dt>Analysis model</dt><dd>{versions.analysisModel}</dd></div>
            </dl>
            <button className="insight-retry" type="button" onClick={() => window.location.reload()}>
              Reload application
            </button>
          </div>
        </div>
      </section>
    );
  }

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

      {analysisOutdated
        && analysisConfig?.enabled
        && analysisConfig.configured
        && !showExternalConfirmation
        && !outdatedNeedsConfirmation
        && !error && (
        <div className="insight-status" role="status">
          <Loader2 className="spin" size={18} />
          <div>
            <strong>Updating analysis</strong>
            <p>The saved result used an older source or analysis version and is hidden until it is refreshed.</p>
          </div>
        </div>
      )}

      {analysisOutdated
        && analysisConfig
        && (!analysisConfig.enabled || !analysisConfig.configured)
        && !error && (
        <div className="parsed-state error" role="alert">
          <AlertCircle size={17} />
          <span>The saved analysis is outdated, and analysis is not available on the server.</span>
          <button className="insight-retry" type="button" onClick={() => runAnalysis()}>
            Try again
          </button>
        </div>
      )}

      {(showExternalConfirmation || outdatedNeedsConfirmation) && analysisConfig && (
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
              onClick={() => {
                setShowExternalConfirmation(false);
                setOutdatedContextKey("");
              }}
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
            <span className="insight-meta-source">
              <FileSearch size={14} />
              Source passages attached
            </span>
            <span className="insight-meta-local">
              {run.provider === "extractive" ? "Runs locally" : "External AI processing"}
            </span>
            <details className="insight-analysis-details">
              <summary>Analysis details</summary>
              <dl>
                <div><dt>Provider</dt><dd>{readable(run.provider)}</dd></div>
                <div><dt>Model</dt><dd>{run.model_name}</dd></div>
                <div><dt>Analysis pipeline</dt><dd>{run.analysis_pipeline_version || run.prompt_version}</dd></div>
                <div><dt>Report schema</dt><dd>{run.schema_version}</dd></div>
                <div><dt>Document type</dt><dd>{readable(report.document_kind)}</dd></div>
                <div><dt>Language</dt><dd>{report.language}</dd></div>
                {run.parser_version && <div><dt>PDF parser</dt><dd>{run.parser_version}</dd></div>}
                {run.parsed_source_hash && <div><dt>Source snapshot</dt><dd>{run.parsed_source_hash}</dd></div>}
                <div><dt>Frontend commit</dt><dd>{run.runtime_versions?.frontendCommit || frontendRuntimeCommit()}</dd></div>
                {run.runtime_versions?.backendCommit && (
                  <div><dt>Backend commit</dt><dd>{run.runtime_versions.backendCommit}</dd></div>
                )}
                {typeof run.citation_coverage === "number" && (
                  <div><dt>Source coverage</dt><dd>{Math.round(run.citation_coverage * 100)}% of displayed claims linked to source passages; passage quality is checked separately</dd></div>
                )}
                {run.provider !== "extractive" && (
                  <div><dt>Data handling</dt><dd>
                    Selected {run.redact_pii ? "redacted " : "unredacted "}document excerpts were sent to the configured provider. API keys stay on the server.
                  </dd></div>
                )}
              </dl>
            </details>
          </div>
          <p className="insight-safety-line">
            {run.provider === "extractive" ? "Local source-based analysis" : "External AI processing"}
            {run.provider !== "extractive" && run.warnings?.includes("pii_redacted") && " · Personal information removed"}
            {run.provider !== "extractive" && run.redact_pii === false && " · Personal information redaction off"}
            {" · Research support only; not medical advice"}
          </p>
          <ReportView
            report={report}
            run={run}
            evidenceById={evidenceById}
            onSelectEvidence={setSelectedEvidence}
            onSaveSuggestion={(suggestion) => {
              void clinicianQuestions.saveQuestion({
                analysisRunId: run.run_id,
                suggestionId: suggestion.id,
              });
            }}
            savedSuggestionIds={clinicianQuestions.savedSuggestionIds}
            staleSuggestionIds={clinicianQuestions.staleSuggestionIds}
            savingSuggestionId={clinicianQuestions.savingSuggestionId}
          />
          {clinicianQuestions.saveError && (
            <div className="parsed-state error">
              <AlertCircle size={17} />
              <span>Could not save this question. Refresh the analysis and try again.</span>
            </div>
          )}
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
          <LiteratureEvidencePanel
            key={`${documentId}:${workspaceId || "default"}:${run.run_id}`}
            documentId={documentId}
            workspaceId={workspaceId}
            analysisRunId={run.run_id}
            onEvidenceClick={(evidenceId) => {
              const evidence = evidenceById.get(evidenceId);
              if (evidence) setSelectedEvidence(evidence);
            }}
          />
          <p className="insight-disclaimer">
            AI-generated document explanation only. It is not a diagnosis or treatment recommendation.
          </p>
        </>
      )}
    </section>
  );
}
