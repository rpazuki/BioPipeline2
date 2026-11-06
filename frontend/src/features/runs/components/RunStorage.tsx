import type { RunSummary } from "@/lib/api";
import { formatBytes } from "@/lib/format";

export function RunStorage({ run }: { run: RunSummary }) {
  return (
    <span title="Current file sizes for inputs, workspace, logs, results, ZIP files, and delivered copies. Hard links count once within this run. Shared source data is excluded.">
      {run.storage_complete === false ? "At least " : ""}
      {formatBytes(run.retained_storage_bytes ?? 0)}
      {run.storage_complete === false ? " (measurement incomplete)" : ""}
    </span>
  );
}
