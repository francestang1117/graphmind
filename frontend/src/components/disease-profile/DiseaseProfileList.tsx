import { FileText, FolderOpen } from "lucide-react";
import type { DiseaseProfileSummary } from "../../services/api";

interface Props {
  profiles: DiseaseProfileSummary[];
  selectedId: string | null;
  loading: boolean;
  onSelect: (conceptId: string) => void;
}

export default function DiseaseProfileList({ profiles, selectedId, loading, onSelect }: Props) {
  if (loading) {
    return <div className="disease-profile-list-state">Loading disease profiles...</div>;
  }
  if (!profiles.length) {
    return (
      <div className="disease-profile-list-state">
        <FolderOpen size={22} />
        <strong>No disease profiles yet</strong>
        <span>Link a classified document below to create one.</span>
      </div>
    );
  }
  return (
    <div className="disease-profile-list" aria-label="Disease profiles">
      {profiles.map((profile) => (
        <button
          className={`disease-profile-list-item ${selectedId === profile.concept_id ? "active" : ""}`}
          key={profile.concept_id}
          type="button"
          onClick={() => onSelect(profile.concept_id)}
        >
          <span className="disease-profile-list-icon"><FileText size={17} /></span>
          <span className="disease-profile-list-copy">
            <strong>{profile.preferred_name_zh || profile.preferred_name_en}</strong>
            <small>{profile.preferred_name_en}</small>
            <small>{profile.document_count} documents · {profile.analysis_count} current analyses</small>
          </span>
        </button>
      ))}
    </div>
  );
}
