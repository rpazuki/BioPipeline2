"use client";

/**
 * Where a run's outputs were sent.
 *
 * Its own panel, above artifacts, because a delivery can fail *after* the run
 * has already succeeded: the researcher sees a green run and an empty folder
 * on the share, and has no way to connect the two. A pending delivery is
 * normal and says so; a failed one carries the reason.
 *
 * Two things a delivered row must show. **The path**, because "it went to the
 * share" is not an answer to where it is — the layout is the platform's
 * invention and nobody has been told it. And on a failed one, **a way to try
 * again**, because most of these failures are an administrator mounting
 * something, after which waiting out a backoff nobody can see serves nobody.
 */

import { DeliveryStatusBadge } from "@/components/ui/StatusBadge";
import { Failure, Loading } from "@/components/ui/states";
import { useRetryDelivery, useRunDeliveries } from "@/features/runs/useRuns";
import { formatTimestamp } from "@/lib/format";

export function DeliveriesPanel({ runId, live }: { runId: string; live: boolean }) {
  const query = useRunDeliveries(runId, live);
  const retry = useRetryDelivery(runId);

  if (query.isPending) return <Loading what="deliveries" />;
  if (query.isError)
    return <Failure error={query.error} onRetry={() => void query.refetch()} />;
  if (query.data.items.length === 0) return null;

  return (
    <section className="panel">
      <h2>Deliveries</h2>
      <ul className="delivery-list">
        {query.data.items.map((delivery) => (
          <li key={delivery.id} className="delivery">
            <div className="delivery__head">
              <DeliveryStatusBadge status={delivery.status} />
              <span className="delivery__field">{delivery.field_key}</span>
              {/* A fanned-out run has one delivery per task under a single
                  field name, so six rows all say `results`. The task key is
                  what answers the question actually being asked: which plate
                  failed to reach the share. */}
              {delivery.task_key ? <code>{delivery.task_key}</code> : null}
              <span className="muted">
                {delivery.mode === "shared"
                  ? `shared storage${delivery.target_root_id ? ` · ${delivery.target_root_id}` : ""}`
                  : "download"}
              </span>
            </div>
            {delivery.target_path ? (
              <p className="delivery__path">
                <code>{delivery.target_path}</code>
              </p>
            ) : null}
            {delivery.message ? <p className="delivery__message">{delivery.message}</p> : null}
            {delivery.delivered_at ? (
              <p className="muted">Delivered {formatTimestamp(delivery.delivered_at)}</p>
            ) : null}
            {delivery.status === "failed" ? (
              <button
                type="button"
                className="button"
                disabled={retry.isPending}
                onClick={() => retry.mutate(delivery.id)}
              >
                {retry.isPending ? "Queueing…" : "Try again"}
              </button>
            ) : null}
            {/* An attempt that has not succeeded yet, but has not given up
                either. Saying how many times it has tried is the difference
                between "waiting" and "failing every few minutes". */}
            {delivery.status === "pending" && delivery.attempts > 0 ? (
              <p className="muted">
                {delivery.attempts} attempt{delivery.attempts === 1 ? "" : "s"} so far
                {delivery.next_attempt_at
                  ? `; next ${formatTimestamp(delivery.next_attempt_at)}`
                  : ""}
                .
              </p>
            ) : null}
          </li>
        ))}
      </ul>
      {retry.isError ? <Failure error={retry.error} /> : null}
    </section>
  );
}
