import type { DiseaseProfileStats as Stats } from "../../services/api";

interface Props {
  stats: Stats;
}

const STAT_ITEMS: Array<{ key: keyof Stats; label: string }> = [
  { key: "document_count", label: "Documents" },
  { key: "research_paper_count", label: "Research papers" },
  { key: "guideline_count", label: "Guidelines" },
  { key: "valid_analysis_count", label: "Current analyses" },
  { key: "expired_analysis_count", label: "Outdated analyses" },
  { key: "external_article_count", label: "External studies" },
  { key: "flagged_article_count", label: "Flagged studies" },
  { key: "human_study_count", label: "Human studies" },
  { key: "animal_study_count", label: "Animal studies" },
  { key: "in_vitro_study_count", label: "In vitro studies" },
  { key: "sample_size_reported_count", label: "Sample size reported" },
  { key: "sample_size_not_reported_count", label: "Sample size missing" },
];

export default function DiseaseProfileStats({ stats }: Props) {
  return (
    <section className="disease-profile-stats" aria-label="Profile statistics">
      {STAT_ITEMS.map(({ key, label }) => (
        <div className="disease-profile-stat" key={key}>
          <strong>{stats[key]}</strong>
          <span>{label}</span>
        </div>
      ))}
    </section>
  );
}
