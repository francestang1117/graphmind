import { AlertTriangle, Info } from "lucide-react";

interface Props {
  warnings: string[];
  excludedCount?: number;
  olderAnalysis?: boolean;
  staleMetadata?: boolean;
}

function warningLabel(warning: string) {
  const labels: Record<string, string> = {
    article_metadata_changed: "Some PubMed metadata changed after matching; review those cards before relying on them.",
    retracted_after_matching: "A previously matched article was later retracted and has been excluded from the visible candidates.",
    retracted: "Retracted articles were excluded from the visible candidates.",
    retraction_notice: "Articles with retraction notices were excluded from the visible candidates.",
  };
  return labels[warning] || warning.replaceAll("_", " ");
}

export default function LiteratureEvidenceAlerts({
  warnings,
  excludedCount = 0,
  olderAnalysis = false,
  staleMetadata = false,
}: Props) {
  const uniqueWarnings = [...new Set(warnings)].filter((warning) => (
    !staleMetadata || warning !== "article_metadata_changed"
  ));
  if (!uniqueWarnings.length && !excludedCount && !olderAnalysis && !staleMetadata) return null;

  return (
    <div className="literature-alert-stack" role="status">
      {olderAnalysis && (
        <div className="literature-alert literature-alert-warning">
          <AlertTriangle size={16} />
          <p>This result belongs to an older medical analysis and is hidden until it is matched to the current analysis.</p>
        </div>
      )}
      {staleMetadata && (
        <div className="literature-alert literature-alert-warning">
          <AlertTriangle size={16} />
          <p>PubMed metadata changed after this match was saved. Review the article details or run matching again.</p>
        </div>
      )}
      {uniqueWarnings.map((warning) => (
        <div className="literature-alert" key={warning}>
          <AlertTriangle size={16} />
          <p>{warningLabel(warning)}</p>
        </div>
      ))}
      {excludedCount > 0 && (
        <div className="literature-alert literature-alert-info">
          <Info size={16} />
          <p>{excludedCount} article{excludedCount === 1 ? "" : "s"} excluded because of retraction status.</p>
        </div>
      )}
    </div>
  );
}
