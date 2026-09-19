import { AlertCircle, FileWarning, RefreshCw } from "lucide-react";
import type { UnassignedDiseaseDocument } from "../../services/api";
import DiseaseConceptPicker from "./DiseaseConceptPicker";

interface Props {
  documents: UnassignedDiseaseDocument[];
  total: number;
  loading: boolean;
  loadingMore: boolean;
  hasMore: boolean;
  error: unknown;
  linking: boolean;
  onLink: (input: { documentId: string; conceptId: string; matchedAlias: string }) => void;
  onLoadMore: () => void;
  onRetry: () => void;
}

export default function UnassignedDocuments({
  documents,
  total,
  loading,
  loadingMore,
  hasMore,
  error,
  linking,
  onLink,
  onLoadMore,
  onRetry,
}: Props) {
  return (
    <section className="disease-unassigned">
      <div className="disease-unassigned-heading">
        <div><span className="disease-profile-eyebrow">Needs review</span><h2>Unassigned medical documents</h2></div>
        <span className="disease-unassigned-count">{total}</span>
      </div>
      <p>Choose a disease from the local dictionary to place a classified document in a research profile.</p>
      {loading && <div className="disease-profile-section-loading">Loading unassigned documents...</div>}
      {Boolean(error) && !loading && (
        <div className="disease-profile-inline-error" role="alert">
          <AlertCircle size={14} />
          <span>Could not load unassigned documents.</span>
          <button type="button" onClick={onRetry}><RefreshCw size={14} /> Retry</button>
        </div>
      )}
      {!loading && !error && !documents.length && <div className="disease-unassigned-empty"><FileWarning size={18} /> All classified documents are assigned.</div>}
      <div className="disease-unassigned-list">
        {documents.map((document) => (
          <article className="disease-unassigned-item" key={document.document_id}>
            <div>
              <strong>{document.title}</strong>
              <span>{document.document_kind} · {document.language}{document.document_date ? ` · ${document.document_date}` : ""}</span>
            </div>
            <DiseaseConceptPicker document={document} busy={linking} onLink={onLink} />
          </article>
        ))}
      </div>
      {hasMore && (
        <button type="button" className="disease-profile-load-more" onClick={onLoadMore} disabled={loadingMore}>
          {loadingMore ? "Loading..." : "Load more documents"}
        </button>
      )}
    </section>
  );
}
