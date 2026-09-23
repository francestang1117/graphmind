export const EXPECTED_PARSER_VERSION = "document-parser-pdf-readable-v6";
export const EXPECTED_ANALYSIS_PIPELINE_VERSION = "medical-insights-readable-v6";
export const EXPECTED_INSIGHT_CONTRACT_VERSION = "medical-insights-readable-v6";

export interface MedicalRuntimeVersions {
  frontendCommit: string;
  backendCommit: string;
  parserVersion: string;
  analysisPipelineVersion: string;
  insightContractVersion: string;
  analysisModel: string;
}

export class ApplicationUpdateIncompleteError extends Error {
  readonly code: string;
  readonly versions: MedicalRuntimeVersions;

  constructor(versions: MedicalRuntimeVersions) {
    super("The frontend and backend medical analysis versions do not match.");
    this.name = "ApplicationUpdateIncompleteError";
    this.code = "application_update_incomplete";
    this.versions = versions;
  }
}

const frontendCommit = import.meta.env.VITE_APP_COMMIT?.trim() || "unknown";

export function frontendRuntimeCommit() {
  return frontendCommit;
}

export function validateMedicalRuntimeHeaders(
  headers: Record<string, unknown>,
): MedicalRuntimeVersions {
  const versions: MedicalRuntimeVersions = {
    frontendCommit,
    backendCommit: String(headers["x-graphmind-backend-commit"] || "unknown"),
    parserVersion: String(headers["x-graphmind-parser-version"] || "unknown"),
    analysisPipelineVersion: String(
      headers["x-graphmind-analysis-pipeline"] || "unknown",
    ),
    insightContractVersion: String(
      headers["x-graphmind-insight-contract"] || "unknown",
    ),
    analysisModel: String(headers["x-graphmind-analysis-model"] || "unknown"),
  };

  const commitMismatch =
    versions.frontendCommit !== "unknown"
    && versions.backendCommit !== "unknown"
    && versions.frontendCommit !== versions.backendCommit;
  const contractMismatch =
    versions.parserVersion !== EXPECTED_PARSER_VERSION
    || versions.analysisPipelineVersion !== EXPECTED_ANALYSIS_PIPELINE_VERSION
    || versions.insightContractVersion !== EXPECTED_INSIGHT_CONTRACT_VERSION
    || (versions.analysisModel.startsWith("extractive-")
      && versions.analysisModel !== "extractive-v3");

  if (commitMismatch || contractMismatch) {
    throw new ApplicationUpdateIncompleteError(versions);
  }
  return versions;
}
