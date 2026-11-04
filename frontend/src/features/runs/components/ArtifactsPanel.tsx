"use client";

/**
 * A run's outputs, and how to get them.
 *
 * Offers the download methods frozen for the run: individual files,
 * directory browsing, and background ZIP preparation. The browser streams
 * completed downloads directly from the server.
 */

import { useState } from "react";

import { DataTable, type Column } from "@/components/ui/DataTable";
import { Failure, Loading } from "@/components/ui/states";
import { useApi } from "@/features/auth/session";
import { useArtifact, useRunArtifacts } from "@/features/runs/useRuns";
import { artifacts, type ArtifactFile, type ArtifactSummary } from "@/lib/api";
import { formatBytes, formatTimestamp } from "@/lib/format";
import { ResultBundle } from "./ResultBundle";

function ArtifactFiles({ artifactId }: { artifactId: string }) {
  const client = useApi();
  const query = useArtifact(artifactId);

  if (query.isPending) return <Loading what="the files in this output" />;
  if (query.isError)
    return <Failure error={query.error} onRetry={() => void query.refetch()} />;
  if (!query.data.available) {
    return <p className="muted">{query.data.unavailable_reason}</p>;
  }
  const files = query.data.files ?? [];
  if (files.length === 0) return <p className="muted">This output is empty.</p>;

  return (
    <ul className="file-list">
      {files.map((file: ArtifactFile) => (
        <li key={file.path}>
          <a href={artifacts.fileHref(client, artifactId, file.path)} download>
            {file.path}
          </a>{" "}
          <span className="muted">{formatBytes(file.size_bytes)}</span>
        </li>
      ))}
    </ul>
  );
}

export function ArtifactsPanel({
  runId,
  live,
  resultDelivery = ["individual"],
}: {
  runId: string;
  live: boolean;
  resultDelivery?: string[];
}) {
  const client = useApi();
  const query = useRunArtifacts(runId, live);
  const [opened, setOpened] = useState<string | null>(null);

  const columns: Column<ArtifactSummary>[] = [
    { key: "filename", header: "File", render: (artifact) => artifact.filename },
    { key: "kind", header: "Kind", render: (artifact) => artifact.kind.replace(/_/g, " ") },
    { key: "size", header: "Size", render: (artifact) => formatBytes(artifact.size_bytes) },
    {
      key: "get",
      header: "",
      render: (artifact) =>
        artifact.kind === "task_output" && !resultDelivery.includes("individual") ? (
          <span className="muted">Included in results ZIP</span>
        ) : artifact.is_directory ? (
          <button
            type="button"
            className="button btn"
            aria-expanded={opened === artifact.id}
            onClick={() => setOpened(opened === artifact.id ? null : artifact.id)}
          >
            {opened === artifact.id ? "Hide files" : "Files"}
          </button>
        ) : (
          // A plain link, not a fetch: the browser streams it, supports
          // ranges, and resumes a twenty-gigabyte transfer rather than
          // restarting it.
          //
          // `download` is honoured only same-origin, which production is and
          // development is not. What makes both behave the same is the
          // server's `Content-Disposition: attachment` — the attribute is the
          // hint, the header is the rule.
          <a
            className="button btn button--primary btn-primary"
            href={artifacts.downloadHref(client, artifact.id)}
            download={artifact.filename}
          >
            Download
          </a>
        ),
    },
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

  return (
    <section className="panel card card-body stack">
      <h2>Outputs</h2>
      {resultDelivery.includes("zip") &&
      query.data?.items.some((artifact) => artifact.kind === "task_output") ? (
        <ResultBundle runId={runId} live={live} />
      ) : null}
      {query.isPending ? <Loading what="outputs" /> : null}
      {query.isError ? (
        <Failure error={query.error} onRetry={() => void query.refetch()} />
      ) : null}
      {query.data ? (
        <DataTable
          caption="Artifacts produced by this run"
          rows={query.data.items}
          columns={columns}
          rowKey={(artifact) => artifact.id}
          emptyMessage="No outputs have been promoted yet."
        />
      ) : null}
      {opened ? (
        <div className="panel card card-body panel--inset stack">
          <h3>Files</h3>
          <ArtifactFiles artifactId={opened} />
        </div>
      ) : null}
    </section>
  );
}
