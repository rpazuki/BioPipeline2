"use client";

/**
 * What one task printed.
 *
 * The first question about a failed task, and for a long time the answer was
 * on a worker's disk where nobody could reach it.
 *
 * Two things this has to say rather than leave to be inferred. That it is
 * showing the **tail** — an aligner prints for hours and what is on screen is
 * the end of it — with the whole log a download away. And that a running
 * attempt is **live**, so the same panel a minute later has more in it; the
 * server says which, and the polling follows that rather than guessing from
 * the task's status.
 */

import { useState } from "react";

import { Failure, Loading } from "@/components/ui/states";
import { useApi } from "@/features/auth/session";
import { useTaskAttempts, useTaskLog } from "@/features/runs/useRuns";
import { artifacts, type AttemptSummary } from "@/lib/api";
import { ApiError } from "@/lib/errors";
import { formatBytes, formatRelative } from "@/lib/format";

function Attempts({
  attempts,
  chosen,
  onChoose,
}: {
  attempts: AttemptSummary[];
  chosen: number | null;
  onChoose: (attempt: number | null) => void;
}) {
  // One attempt needs no chooser; several are the reason this exists, because
  // the first failure is the evidence for why there was a retry.
  if (attempts.length < 2) return null;
  return (
    <div className="button-row">
      {attempts.map((attempt) => {
        const on =
          chosen === attempt.attempt_number || (chosen === null && attempt === attempts[0]);
        return (
          <button
            key={attempt.id}
            type="button"
            className={on ? "button button--primary" : "button"}
            aria-pressed={on}
            onClick={() => onChoose(attempt.attempt_number)}
          >
            Attempt {attempt.attempt_number}
            {attempt.exit_code !== null && attempt.exit_code !== undefined
              ? ` (exit ${attempt.exit_code})`
              : ""}
          </button>
        );
      })}
    </div>
  );
}

export function TaskLog({ runId, taskId }: { runId: string; taskId: string }) {
  const client = useApi();
  const [attempt, setAttempt] = useState<number | null>(null);
  const attempts = useTaskAttempts(runId, taskId);
  const log = useTaskLog(runId, taskId, attempt);

  if (log.isPending) return <Loading what="this task's log" />;
  if (log.isError) {
    // A task nothing has attempted is an ordinary state, not a failure. It
    // is asked of the server rather than inferred from `attempt_count`,
    // which a different function maintains and which disagrees the moment
    // anything runs a task outside the claim path.
    if (log.error instanceof ApiError && log.error.code === "task.no_attempt") {
      return <p className="muted">This task has not run yet, so there is nothing to show.</p>;
    }
    return <Failure error={log.error} onRetry={() => void log.refetch()} />;
  }

  return (
    <div className="stack stack--tight">
      <Attempts attempts={attempts.data?.items ?? []} chosen={attempt} onChoose={setAttempt} />

      <div className="log__meta">
        {log.data.live ? (
          <span className="badge badge--running">still running</span>
        ) : (
          <span className="muted">attempt {log.data.attempt_number}</span>
        )}
        {log.data.truncated ? (
          <span className="muted">
            showing the last {formatBytes(log.data.bytes_read)} of{" "}
            {formatBytes(log.data.bytes_total)}
          </span>
        ) : null}
        {log.data.artifact_id ? (
          <a
            className="button"
            href={artifacts.downloadHref(client, log.data.artifact_id)}
            download
          >
            Download the whole log
          </a>
        ) : null}
      </div>

      {log.data.message ? (
        <p className="muted">{log.data.message}</p>
      ) : (
        // `pre` rather than a virtualised viewer: the tail is bounded by the
        // server, so what arrives here is always small enough to render.
        <pre className="log" tabIndex={0} aria-label="Task log">
          {log.data.text}
        </pre>
      )}

      {log.data.live ? (
        <p className="muted">
          Updated every few seconds while the task runs. Last read{" "}
          {formatRelative(new Date(log.dataUpdatedAt).toISOString())}.
        </p>
      ) : null}
    </div>
  );
}
