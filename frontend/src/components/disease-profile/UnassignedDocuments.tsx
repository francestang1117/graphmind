import { FileWarning } from "lucide-react";
import type { UnassignedDiseaseDocument } from "../../services/api";
import DiseaseConceptPicker from "./DiseaseConceptPicker";

interface Props {
  documents: UnassignedDiseaseDocument[];
  loading: boolean;
  linking: boolean;
  onLink: (input: { documentId: string; conceptId: string; matchedAlias: string }) => void;
}

export default function UnassignedDocuments({ documents, loading, linking, onLink }: Props) {
  return (
    <section className="disease-unassigned">
      <div className="disease-unassigned-heading">
        <div><span className="disease-profile-eyebrow">Needs review</span><h2>Unassigned medical documents</h2></div>
        <span className="disease-unassigned-count">{documents.length}</span>
      </div>
      <p>Choose a disease from the local dictionary to place a classified document in a research profile.</p>
      {loading && <div className="disease-profile-section-loading">Loading unassigned documents...</div>}
      {!loading && !documents.length && <div className="disease-unassigned-empty"><FileWarning size={18} /> All classified documents are assigned.</div>}
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
    </section>
  );
}
