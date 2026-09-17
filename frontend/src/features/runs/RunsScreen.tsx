"use client";

/**
 * My Runs — or everyone's, for an admin. The backend decides which; this
 * screen does not know the difference and must not pretend to.
 */

import { useRouter } from "next/navigation";
import { useState } from "react";

import { DataTable, type Column } from "@/components/ui/DataTable";
import { RunStatusBadge } from "@/components/ui/StatusBadge";
import { Empty, Failure, Loading } from "@/components/ui/states";
import { useRunList } from "@/features/runs/useRuns";
import type { RunStatus, RunSummary, RunTrigger } from "@/lib/api";
import { formatDuration, formatRelative, shortId } from "@/lib/format";

/**
 * Every run status, as filter options.
 *
 * Typed as the union so the list cannot fall behind the backend — and it is
 * spelled out rather than derived because the *order* is a judgement: the
 * states people look for are at the front.
 */
const FILTERS: { value: RunStatus | ""; label: string }[] = [
  { value: "", label: "All" },
  { value: "running", label: "Running" },
  { value: "queued", label: "Queued" },
  { value: "failed", label: "Failed" },
  { value: "succeeded", label: "Succeeded" },
  { value: "blocked", label: "Blocked" },
  { value: "cancel_requested", label: "Cancelling" },
  { value: "cancelled", label: "Cancelled" },
];

/**
 * What started a run, where it is not obvious.
 *
 * A manual run needs no explanation; one a clock started does, because the
 * first question about a run somebody does not remember submitting is whether
 * they submitted it.
 */
const STARTED_BY: Record<RunTrigger, string | null> = {
  manual: null,
  api: "via the API",
  admin: "by an administrator",
  schedule: "on a schedule",
};

export function RunsScreen() {
  const router = useRouter();
  const [status, setStatus] = useState<RunStatus | "">("");
  const query = useRunList(status);

  const columns: Column<RunSummary>[] = [
    {
      key: "status",
      header: "Status",
      render: (run) => <RunStatusBadge status={run.status} />,
    },
    {
      key: "id",
      header: "Run",
      render: (run) => <code>{shortId(run.id)}</code>,
    },
    {
      key: "submitted",
      header: "Submitted",
      render: (run) => (
        <div className="stack stack--tight">
          <span>{formatRelative(run.created_at)}</span>
          {STARTED_BY[run.requested_from] ? (
            <span className="muted">{STARTED_BY[run.requested_from]}</span>
          ) : null}
        </div>
      ),
    },
    {
      key: "duration",
      header: "Duration",
      render: (run) => formatDuration(run.started_at, run.finished_at),
      secondary: true,
    },
    {
      key: "revision",
      header: "Pipeline revision",
      render: (run) => <code>{shortId(run.pipeline_revision_id)}</code>,
      secondary: true,
    },
  ];

  return (
    <div className="stack">
      <header className="page-header">
        <h1>Runs</h1>
        <div className="filters">
          <label className="visually-hidden" htmlFor="run-status-filter">
            Filter by status
          </label>
          <select
            id="run-status-filter"
            value={status}
            onChange={(event) => setStatus(event.target.value as RunStatus | "")}
          >
            {FILTERS.map((filter) => (
              <option key={filter.value || "all"} value={filter.value}>
                {filter.label}
              </option>
            ))}
          </select>
        </div>
      </header>

      {query.isPending ? <Loading what="runs" /> : null}
      {query.isError ? (
        <Failure error={query.error} onRetry={() => void query.refetch()} />
      ) : null}

      {query.data ? (
        query.data.items.length === 0 && !status ? (
          <Empty
            title="No runs yet."
            detail="A run starts from a pipeline revision. Ask an administrator to publish one, or open Pipelines if you are one."
          />
        ) : (
          <DataTable
            caption="Runs"
            rows={query.data.items}
            columns={columns}
            rowKey={(run) => run.id}
            onOpen={(run) => router.push(`/runs/${run.id}`)}
            emptyMessage={`No ${status.replace(/_/g, " ")} runs.`}
          />
        )
      ) : null}
    </div>
  );
}
