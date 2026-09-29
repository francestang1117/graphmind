import type { MedicalInsightEvidence } from "../../../services/api";

export function evidenceClaimKey(findingId: string, evidenceId: string) {
  return `${findingId}\u0000${evidenceId}`;
}

export interface MedicalInsightEvidenceIndexes {
  byClaim: Map<string, MedicalInsightEvidence>;
  bySource: Map<string, MedicalInsightEvidence>;
}

/**
 * Keep claim-specific citation rows separate from the deduplicated source list.
 * The same parser chunk may support several claims with different excerpts.
 */
export function buildMedicalInsightEvidenceIndexes(
  evidence: MedicalInsightEvidence[],
): MedicalInsightEvidenceIndexes {
  const byClaim = new Map<string, MedicalInsightEvidence>();
  const bySource = new Map<string, MedicalInsightEvidence>();

  for (const item of evidence) {
    byClaim.set(evidenceClaimKey(item.finding_id, item.evidence_id), item);
    const existing = bySource.get(item.evidence_id);
    if (!existing || item.quote.length > existing.quote.length) {
      bySource.set(item.evidence_id, item);
    }
  }

  return { byClaim, bySource };
}
