"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import Link from "next/link";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { Empty, Failure, Loading } from "@/components/ui/states";
import { useApi } from "@/features/auth/session";
import type { AuditEvent, Page } from "@/lib/api";
import { formatTimestamp } from "@/lib/format";

interface Deletion {
  id: string;
  target_type: string;
  target_key: string;
  name?: string | null;
  requested_by: string;
  requested_by_name?: string | null;
  requested_by_email?: string | null;
  status: string;
  error: string | null;
  created_at: string;
  completed_at: string | null;
}

export function AuditScreen() {
  const client = useApi();
  const cache = useQueryClient();
  const [kind, setKind] = useState("run");
  const [action, setAction] = useState("");
  const [target, setTarget] = useState("");
  const [draft, setDraft] = useState("");
  const [offset, setOffset] = useState(0);
  const events = useQuery({
    queryKey: ["audit-page", kind, action, target, offset],
    queryFn: () =>
      client.get<Page<AuditEvent>>("/admin/audit-events", {
        query: {
          target_type: kind || undefined,
          action: action || undefined,
          target_id: target || undefined,
          offset,
          limit: 50,
        },
      }),
    refetchInterval: 5000,
  });
  const deletions = useQuery({
    queryKey: ["deletions"],
    queryFn: () => client.get<{ items: Deletion[] }>("/admin/deletions"),
    refetchInterval: 5000,
  });
  const retry = useMutation({
    mutationFn: (id: string) => client.post(`/admin/deletions/${id}/retry`),
    onSuccess: () => {
      void cache.invalidateQueries({ queryKey: ["deletions"] });
      void cache.invalidateQueries({ queryKey: ["audit-page"] });
    },
  });
  const columns: Column<AuditEvent>[] = [
    { key: "when", header: "When", render: (row) => formatTimestamp(row.created_at) },
    { key: "action", header: "Event", render: (row) => <code>{row.action}</code> },
    { key: "who", header: "User", render: (row) => row.actor_email || "System" },
    {
      key: "target",
      header: "Resource",
      render: (row) => (
        <span>
          {row.target_type}
          <br />
          <code>{row.target_id}</code>
        </span>
      ),
    },
    {
      key: "details",
      header: "Details",
      render: (row) => (
        <details>
          <summary>View details</summary>
          <pre className="log">{JSON.stringify(row.details, null, 2)}</pre>
        </details>
      ),
    },
  ];
  const cleanupColumns: Column<Deletion>[] = [
    {
      key: "user",
      header: "User",
      render: (row) => (
        <div className="stack stack--tight">
          <span>{row.requested_by_name || row.requested_by_email || row.requested_by}</span>
          {row.requested_by_name && row.requested_by_email ? (
            <small className="muted">{row.requested_by_email}</small>
          ) : null}
        </div>
      ),
    },
    {
      key: "target",
      header: "Resource",
      render: (row) => (
        <span>
          {row.target_type}: {row.name || row.target_key}
        </span>
      ),
    },
    {
      key: "status",
      header: "Cleanup",
      render: (row) => (
        <span
          className={`badge badge--${row.status === "complete" ? "good" : row.status === "failed" ? "bad" : "running"}`}
        >
          {row.status}
        </span>
      ),
    },
    { key: "when", header: "Requested", render: (row) => formatTimestamp(row.created_at) },
    {
      key: "error",
      header: "Result",
      render: (row) =>
        row.error ||
        (row.completed_at
          ? `Completed ${formatTimestamp(row.completed_at)}`
          : "Waiting for background cleanup"),
    },
    {
      key: "retry",
      header: "Actions",
      render: (row) =>
        row.status === "failed" ? (
          <button
            className="btn"
            disabled={retry.isPending}
            onClick={() => retry.mutate(row.id)}
          >
            Retry cleanup
          </button>
        ) : null,
    },
  ];
  return (
    <div className="stack">
      <header className="page-header">
        <div>
          <h1>Audit</h1>
          <p className="muted">
            Run submissions, status changes, and resource deletions. History remains after
            deletion.
          </p>
        </div>
        <Link className="btn" href="/runs">
          Runs
        </Link>
      </header>
      <form
        className="filters"
        onSubmit={(event) => {
          event.preventDefault();
          setTarget(draft.trim());
          setOffset(0);
        }}
      >
        <label>
          Resource type
          <select
            className="form-select"
            value={kind}
            onChange={(event) => {
              setKind(event.target.value);
              setOffset(0);
            }}
          >
            <option value="">Everything</option>
            <option value="run">Runs</option>
            <option value="publication">Publications</option>
            <option value="pipeline_revision">Pipeline versions</option>
            <option value="component">Components</option>
            <option value="user">Accounts</option>
            <option value="environment">Environments</option>
          </select>
        </label>
        <label>
          Event
          <select
            className="form-select"
            value={action}
            onChange={(event) => {
              setAction(event.target.value);
              setOffset(0);
            }}
          >
            <option value="">All events</option>
            {[
              "run.submitted",
              "run.status_changed",
              "run.imported_history",
              "run.deletion_requested",
              "run.deleted",
              "run.deletion_failed",
              "publication.deleted",
              "pipeline_revision.deleted",
              "component.deleted",
            ].map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
        </label>
        <label>
          Run or resource identifier
          <input
            className="form-control"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Full resource identifier"
          />
        </label>
        <button type="submit" className="btn btn-primary">
          Search audit
        </button>
      </form>
      {events.isPending ? (
        <Loading what="audit history" />
      ) : events.isError ? (
        <Failure error={events.error} />
      ) : events.data.items.length ? (
        <DataTable
          caption="Audit history"
          rows={events.data.items}
          columns={columns}
          rowKey={(row) => row.id}
        />
      ) : (
        <Empty title="No matching audit records." />
      )}
      <div className="button-row">
        <button
          className="btn"
          disabled={offset === 0}
          onClick={() => setOffset(Math.max(0, offset - 50))}
        >
          Newer
        </button>
        <span>
          Records {offset + 1}–{offset + (events.data?.items.length || 0)}
        </span>
        <button
          className="btn"
          disabled={(events.data?.items.length || 0) < 50}
          onClick={() => setOffset(offset + 50)}
        >
          Older
        </button>
      </div>
      <section className="stack">
        <h2>Deletion and file cleanup</h2>
        <p className="muted">
          Pending cleanup runs in the background. Failed cleanup retains its audit record and
          can be retried after correcting the reported problem.
        </p>
        {retry.isError ? <Failure error={retry.error} /> : null}
        {deletions.isPending ? (
          <Loading what="deletion requests" />
        ) : deletions.isError ? (
          <Failure error={deletions.error} />
        ) : deletions.data.items.length ? (
          <DataTable
            caption="Deletion requests"
            rows={deletions.data.items}
            columns={cleanupColumns}
            rowKey={(row) => row.id}
          />
        ) : (
          <Empty title="No deletion requests." />
        )}
      </section>
    </div>
  );
}
