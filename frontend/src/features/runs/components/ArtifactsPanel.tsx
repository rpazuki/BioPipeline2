"use client";

import { DataTable, type Column } from "@/components/ui/DataTable";
import { Failure, Loading } from "@/components/ui/states";
import { useRunArtifacts } from "@/features/runs/useRuns";
import type { ArtifactSummary } from "@/lib/api";
import { formatBytes, formatTimestamp } from "@/lib/format";

const COLUMNS: Column<ArtifactSummary>[] = [
  { key: "filename", header: "File", render: (artifact) => artifact.filename },
  { key: "kind", header: "Kind", render: (artifact) => artifact.kind.replace(/_/g, " ") },
  { key: "size", header: "Size", render: (artifact) => formatBytes(artifact.size_bytes) },
  {
    key: "expires",
    header: "Expires",
    // Retention is finite, and an output that vanishes unannounced is how a
    // researcher loses a result they assumed was archived.
    render: (artifact) =>
      artifact.expires_at ? formatTimestamp(artifact.expires_at) : "does not expire",
    secondary: true,
  },
  {
    key: "checksum",
    header: "Checksum",
    render: (artifact) =>
      artifact.checksum_sha256 ? <code>{artifact.checksum_sha256.slice(0, 12)}</code> : "—",
    secondary: true,
  },
];

export function ArtifactsPanel({ runId, live }: { runId: string; live: boolean }) {
  const query = useRunArtifacts(runId, live);

  return (
    <section className="panel">
      <h2>Outputs</h2>
      {query.isPending ? <Loading what="outputs" /> : null}
      {query.isError ? (
        <Failure error={query.error} onRetry={() => void query.refetch()} />
      ) : null}
      {query.data ? (
        <DataTable
          caption="Artifacts produced by this run"
          rows={query.data.items}
          columns={COLUMNS}
          rowKey={(artifact) => artifact.id}
          emptyMessage="No outputs have been promoted yet."
        />
      ) : null}
      <p className="muted">
        The API does not serve artifact downloads yet; these are the promoted files and their
        checksums.
      </p>
    </section>
  );
}
