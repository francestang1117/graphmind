import { Activity, CheckCircle2, Database, FileText } from "lucide-react";
import type { FileInfo } from "../../stores/appStore";
import type { UploadState } from "../../hooks/useUpload";
import { formatSize } from "../../utils/fileMeta";

interface Props {
  files: FileInfo[];
  uploads: UploadState[];
}

export default function DocumentOverview({ files, uploads }: Props) {
  // Count in-flight uploads too, since they are already visible in the list.
  const readyCount = files.filter((file) => (file.status ?? "done") === "done").length;
  const indexingCount =
    files.filter((file) => (file.status ?? "done") === "processing").length +
    uploads.filter((upload) => upload.status === "uploading").length;
  const totalBytes =
    files.reduce((sum, file) => sum + file.file_size, 0) +
    uploads.reduce((sum, upload) => sum + upload.file_size, 0);

  const cards = [
    { label: "Total files", value: files.length + uploads.length, icon: FileText, tone: "violet" },
    { label: "Ready", value: readyCount, icon: CheckCircle2, tone: "green" },
    { label: "Active", value: indexingCount, icon: Activity, tone: "blue" },
    { label: "Stored", value: formatSize(totalBytes), icon: Database, tone: "amber" },
  ];

  return (
    <section className="document-overview" aria-label="Document overview">
      {cards.map((card) => {
        const Icon = card.icon;
        return (
          <div className="overview-card" key={card.label}>
            <span className={`overview-icon ${card.tone}`}>
              <Icon size={15} />
            </span>
            <div>
              <strong>{card.value}</strong>
              <span>{card.label}</span>
            </div>
          </div>
        );
      })}
    </section>
  );
}
