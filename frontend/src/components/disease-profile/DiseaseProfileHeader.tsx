import { ExternalLink, ShieldCheck } from "lucide-react";
import type { DiseaseProfileDetail } from "../../services/api";

interface Props {
  profile: DiseaseProfileDetail;
  onOpenVisitPrep: () => void;
}

export default function DiseaseProfileHeader({ profile, onOpenVisitPrep }: Props) {
  return (
    <header className="disease-profile-header">
      <div>
        <span className="disease-profile-eyebrow">Disease research profile</span>
        <h2>{profile.preferred_name_zh || profile.preferred_name_en}</h2>
        <p>{profile.preferred_name_en} · Based on current documents in this research project.</p>
      </div>
      <div className="disease-profile-header-actions">
        <button type="button" className="disease-profile-secondary-button" onClick={onOpenVisitPrep}>
          <ExternalLink size={15} />
          Visit Prep
        </button>
        <div className="disease-profile-version" title="Local ontology version">
          <ShieldCheck size={15} />
          {profile.ontology_version}
        </div>
      </div>
    </header>
  );
}
