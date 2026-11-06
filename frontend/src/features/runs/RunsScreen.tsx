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
import { RunStorage } from "@/features/runs/components/RunStorage";
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
  const [searchText, setSearchText] = useState("");
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const query = useRunList(status, search, offset);

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
      key: "user",
      header: "User",
      render: (run) => (
        <div className="stack stack--tight">
          <span>{run.requested_by_name || run.requested_by}</span>
          {run.requested_by_email ? (
            <span className="muted">{run.requested_by_email}</span>
          ) : null}
        </div>
      ),
    },
    {
      key: "catalogue",
      header: "Catalogue",
      render: (run) => run.catalogue_name || "Direct run",
    },
    {
      key: "storage",
      header: "Retained storage",
      render: (run) => <RunStorage run={run} />,
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
      </header>
      <form
        className="filters"
        onSubmit={(event) => {
          event.preventDefault();
          setSearch(searchText.trim());
          setOffset(0);
        }}
      >
        <label className="visually-hidden" htmlFor="run-search">
          Search runs
        </label>
        <input
          className="form-control run-search"
          id="run-search"
          type="search"
          placeholder="Search user, catalogue, or run identifier"
          value={searchText}
          onChange={(event) => setSearchText(event.target.value)}
        />
        <button className="button btn btn-primary" type="submit">
          Search
        </button>
        {search || status ? (
          <button
            className="button btn btn-secondary"
            type="button"
            onClick={() => {
              setSearchText("");
              setSearch("");
              setStatus("");
              setOffset(0);
            }}
          >
            Clear filters
          </button>
        ) : null}
        <label className="visually-hidden" htmlFor="run-status-filter">
          Filter by status
        </label>
        <select
          className="form-select"
          id="run-status-filter"
          value={status}
          onChange={(event) => {
            setStatus(event.target.value as RunStatus | "");
            setOffset(0);
          }}
        >
          {FILTERS.map((filter) => (
            <option key={filter.value || "all"} value={filter.value}>
              {filter.label}
            </option>
          ))}
        </select>
      </form>

      {query.isPending ? <Loading what="runs" /> : null}
      {query.isError ? (
        <Failure error={query.error} onRetry={() => void query.refetch()} />
      ) : null}

      {query.data ? (
        query.data.items.length === 0 && !status && !search && offset === 0 ? (
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
            emptyMessage={
              search ? "No runs match these filters." : `No ${status.replace(/_/g, " ")} runs.`
            }
          />
        )
      ) : null}
      {query.data && (offset > 0 || (query.data.total ?? 0) > 50) ? (
        <div className="button-row">
          <button
            className="button btn btn-secondary"
            type="button"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - 50))}
          >
            Newer
          </button>
          <span>
            {query.data.total === 0 ? 0 : offset + 1}–{offset + query.data.items.length} of{" "}
            {query.data.total} runs
          </span>
          <button
            className="button btn btn-secondary"
            type="button"
            disabled={offset + query.data.items.length >= (query.data.total ?? 0)}
            onClick={() => setOffset(offset + 50)}
          >
            Older
          </button>
        </div>
      ) : null}
    </div>
  );
}
