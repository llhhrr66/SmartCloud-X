import { formatStatusLabel, getStatusTone } from "../lib/presenter";

export function StatusBadge({ status }: { status?: string | boolean | null }) {
  const raw = typeof status === "boolean" ? (status ? "enabled" : "disabled") : String(status || "unknown");
  const text = formatStatusLabel(raw);
  const tone = getStatusTone(raw);
  return <span className={`badge badge-${tone}`}>{text}</span>;
}
