"use client";

/**
 * Where a run's outputs were sent.
 *
 * Its own panel, above artifacts, because a delivery can fail *after* the run
 * has already succeeded: the researcher sees a green run and an empty folder
 * on the share, and has no way to connect the two. A pending delivery is
 * normal and says so; a failed one carries the reason.
 */

import { DeliveryStatusBadge } from "@/components/ui/StatusBadge";
import { Failure, Loading } from "@/components/ui/states";
import { useRunDeliveries } from "@/features/runs/useRuns";
import { formatTimestamp } from "@/lib/format";

export function DeliveriesPanel({ runId, live }: { runId: string; live: boolean }) {
  const query = useRunDeliveries(runId, live);

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
              <span className="muted">
                {delivery.mode === "shared"
                  ? `shared storage${delivery.target_root_id ? ` · ${delivery.target_root_id}` : ""}`
                  : "download"}
              </span>
            </div>
            {delivery.message ? <p className="delivery__message">{delivery.message}</p> : null}
            {delivery.delivered_at ? (
              <p className="muted">Delivered {formatTimestamp(delivery.delivered_at)}</p>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}
