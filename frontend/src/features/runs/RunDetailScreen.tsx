"use client";

/**
 * The operational centre of the application.
 *
 * Ordered by what someone actually came here to find out: is it alive, how far
 * has it got, did the outputs reach where they were meant to go, and only then
 * the per-task detail. Deliveries sit above tasks deliberately — a succeeded
 * run with an undelivered output is the failure mode people do not think to
 * look for.
 */

import { useState } from "react";

import { Dialog } from "@/components/ui/Dialog";
import { RunStatusBadge } from "@/components/ui/StatusBadge";
import { SubmittedValue } from "@/features/values/SubmittedValue";
import { Failure, Loading } from "@/components/ui/states";
import { ArtifactsPanel } from "@/features/runs/components/ArtifactsPanel";
import { DeliveriesPanel } from "@/features/runs/components/DeliveriesPanel";
import { TaskProgress } from "@/features/runs/components/TaskProgress";
import { TasksPanel } from "@/features/runs/components/TasksPanel";
import { useCancelRun, useRun } from "@/features/runs/useRuns";
import { isTerminal } from "@/lib/api";
import { formatDuration, formatTimestamp } from "@/lib/format";

export function RunDetailScreen({ runId }: { runId: string }) {
  const query = useRun(runId);
  const cancel = useCancelRun(runId);
  const [confirming, setConfirming] = useState(false);

  if (query.isPending) return <Loading what="this run" />;
  if (query.isError)
    return <Failure error={query.error} onRetry={() => void query.refetch()} />;

  const run = query.data;
  const live = !isTerminal(run.status);
  const values = Object.entries(run.input_values ?? {});

  return (
    <div className="stack">
      <header className="page-header">
        <div>
          <h1>
            Run <code>{run.id}</code>
          </h1>
          <div className="page-header__meta">
            <RunStatusBadge status={run.status} />
            {live ? (
              <span className="muted" aria-live="polite">
                updating every few seconds
              </span>
            ) : null}
          </div>
        </div>
        {live ? (
          <button
            type="button"
            className="button button--danger"
            onClick={() => setConfirming(true)}
            disabled={cancel.isPending || run.status === "cancel_requested"}
          >
            {run.status === "cancel_requested" ? "Cancelling…" : "Cancel run"}
          </button>
        ) : null}
      </header>

      {cancel.isError ? <Failure error={cancel.error} /> : null}

      <section className="panel">
        <TaskProgress counts={run.task_counts ?? {}} total={run.total_tasks ?? 0} />
        <dl className="detail-list">
          <dt>Submitted</dt>
          <dd>{formatTimestamp(run.created_at)}</dd>
          <dt>Started</dt>
          <dd>{run.started_at ? formatTimestamp(run.started_at) : "not yet"}</dd>
          <dt>Finished</dt>
          <dd>{run.finished_at ? formatTimestamp(run.finished_at) : "—"}</dd>
          <dt>Duration</dt>
          <dd>{formatDuration(run.started_at, run.finished_at)}</dd>
          <dt>Pipeline revision</dt>
          <dd>
            <code>{run.pipeline_revision_id}</code>
          </dd>
          {run.environment ? (
            <>
              {/* What it actually ran against, not what is installed now: an
                  install that happened afterwards belongs to somebody else's
                  run. */}
              <dt>Environment</dt>
              <dd>
                {run.environment.environment_name}{" "}
                <span className="muted">
                  · {run.environment.package_count} package
                  {run.environment.package_count === 1 ? "" : "s"}
                  {run.environment.python_version
                    ? ` · Python ${run.environment.python_version}`
                    : ""}
                </span>
                {run.environment.reproducible ? null : (
                  <p className="field__error">{run.environment.note}</p>
                )}
              </dd>
            </>
          ) : null}
          {run.cancel_requested_at ? (
            <>
              <dt>Cancellation requested</dt>
              <dd>{formatTimestamp(run.cancel_requested_at)}</dd>
            </>
          ) : null}
        </dl>
      </section>

      <DeliveriesPanel runId={runId} live={live} />

      <section className="panel">
        <h2>Submitted values</h2>
        {values.length === 0 ? (
          <p className="muted">This run was submitted with no values.</p>
        ) : (
          <dl className="detail-list">
            {values.map(([key, value]) => (
              <div key={key} className="detail-list__pair">
                <dt>{key}</dt>
                <dd>
                  <SubmittedValue value={value} />
                </dd>
              </div>
            ))}
          </dl>
        )}
      </section>

      <TasksPanel runId={runId} live={live} />
      <ArtifactsPanel runId={runId} live={live} />

      <Dialog open={confirming} title="Cancel this run?" onClose={() => setConfirming(false)}>
        <p>
          Queued tasks stop immediately. A task already running is asked to stop and may take a
          little longer. Work already done is not undone.
        </p>
        <div className="dialog__actions">
          <button
            type="button"
            className="button button--quiet"
            onClick={() => setConfirming(false)}
          >
            Keep running
          </button>
          <button
            type="button"
            className="button button--danger"
            onClick={() => {
              cancel.mutate();
              setConfirming(false);
            }}
          >
            Cancel run
          </button>
        </div>
      </Dialog>
    </div>
  );
}
