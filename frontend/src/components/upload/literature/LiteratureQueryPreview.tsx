import { ExternalLink, Loader2, RefreshCw, ShieldCheck } from "lucide-react";
import type { LiteratureConceptSelection, LiteratureSearchPreview } from "../../../services/api";
import DiseaseConceptPicker from "./DiseaseConceptPicker";

interface Props {
  preview: LiteratureSearchPreview;
  selections: LiteratureConceptSelection[];
  onSelectConcept: (matchId: string, conceptId: string) => void;
  onRepreview: () => void;
  onStart: () => void;
  previewLoading: boolean;
  startLoading: boolean;
}

function readable(value: string) {
  return value.replaceAll("_", " ");
}

export default function LiteratureQueryPreview({
  preview,
  selections,
  onSelectConcept,
  onRepreview,
  onStart,
  previewLoading,
  startLoading,
}: Props) {
  const needsConcept = preview.resolution_status !== "ready";
  const external = preview.external_data;

  return (
    <section className="literature-query-preview" aria-labelledby="literature-preview-heading">
      <div className="literature-section-heading">
        <div>
          <span className="section-heading">Before the search</span>
          <h3 id="literature-preview-heading">Review the PubMed query</h3>
        </div>
        <span className={`literature-resolution ${needsConcept ? "needs-confirmation" : "ready"}`}>
          {needsConcept ? "Concept selection needed" : "Ready to search"}
        </span>
      </div>

      <div className="literature-query-box">
        <span>Exact query sent to PubMed</span>
        <code>{preview.pubmed_query || "Select a disease concept to build the query."}</code>
      </div>

      {preview.detected_concepts.length > 0 && (
        <div className="literature-detected-concepts">
          <span className="literature-label">Detected concepts</span>
          <div>
            {preview.detected_concepts.map((concept) => (
              <span className="literature-concept-chip" key={`${concept.type}-${concept.normalized}-${concept.concept_id ?? "raw"}`}>
                {concept.normalized}
                <small>{readable(concept.type)}</small>
              </span>
            ))}
          </div>
        </div>
      )}

      <DiseaseConceptPicker
        matches={preview.ambiguous_concepts}
        selections={selections}
        onSelect={onSelectConcept}
      />

      <div className="literature-disclosure literature-disclosure-compact">
        <ShieldCheck size={16} />
        <div>
          <strong>External data disclosure</strong>
          <p>
            PubMed receives normalized query terms only. Document content and the uploaded file stay on this server.
          </p>
          <span>
            Provider: {external.provider} · Query terms: {external.sends_query_terms ? "yes" : "no"} · Document content: {external.sends_document_content ? "yes" : "no"}
          </span>
          {preview.redacted_fields.length > 0 && (
            <span>Removed locally before search: {preview.redacted_fields.join(", ")}</span>
          )}
        </div>
      </div>

      <div className="literature-preview-footer">
        <span>
          {preview.ontology_version ? `Ontology ${preview.ontology_version}` : "Local terminology"}
          {preview.query_fingerprint ? ` · fingerprint ${preview.query_fingerprint.slice(0, 10)}` : ""}
        </span>
        <div className="literature-action-row">
          {needsConcept && (
            <button className="insight-retry literature-secondary-button" type="button" onClick={onRepreview} disabled={previewLoading}>
              {previewLoading ? <Loader2 className="spin" size={14} /> : <RefreshCw size={14} />}
              Rebuild preview
            </button>
          )}
          <button className="insight-primary-action" type="button" onClick={onStart} disabled={needsConcept || !preview.pubmed_query || startLoading}>
            {startLoading ? <Loader2 className="spin" size={14} /> : <ExternalLink size={14} />}
            Confirm and search
          </button>
        </div>
      </div>
    </section>
  );
}
