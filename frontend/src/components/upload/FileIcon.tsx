import { File } from "lucide-react";
import { fileTypeMeta } from "../../utils/fileMeta";

export default function FileIcon({ ext }: { ext: string }) {
  // Unknown extensions get a quiet default instead of breaking the row layout.
  const meta = fileTypeMeta[ext] ?? { icon: File, tone: "gray" };
  const Icon = meta.icon;

  return (
    <div className={`file-icon ${meta.tone}`}>
      <Icon size={22} />
    </div>
  );
}
