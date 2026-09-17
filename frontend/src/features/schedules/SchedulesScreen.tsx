"use client";

/**
 * What is going to happen, and when.
 *
 * The recurrence is shown as a sentence rather than as an RRULE, and the next
 * window as a real time in a named zone — a schedule nobody can read is a
 * schedule nobody checks, and the first anyone knows is that the results
 * stopped arriving.
 */

import Link from "next/link";
import { useRouter } from "next/navigation";

import { DataTable, type Column } from "@/components/ui/DataTable";
import { ScheduleStatusBadge } from "@/components/ui/StatusBadge";
import { Empty, Failure, Loading } from "@/components/ui/states";
import { describe } from "@/features/schedules/recurrence";
import { useSchedules } from "@/features/schedules/useSchedules";
import type { ScheduleSummary } from "@/lib/api";
import { formatRelative, formatTimestamp } from "@/lib/format";

export function SchedulesScreen() {
  const router = useRouter();
  const query = useSchedules();

  const columns: Column<ScheduleSummary>[] = [
    {
      key: "title",
      header: "Schedule",
      render: (row) => (
        <div className="stack stack--tight">
          <span>{row.title}</span>
          <span className="muted">{row.entry_title}</span>
        </div>
      ),
    },
    {
      key: "when",
      header: "When",
      render: (row) => describe(row.rrule, row.interval_seconds, row.timezone),
    },
    {
      key: "next",
      header: "Next",
      render: (row) =>
        row.next_fire_at ? (
          <span title={formatTimestamp(row.next_fire_at)}>
            {formatRelative(row.next_fire_at)}
          </span>
        ) : (
          <span className="muted">never again</span>
        ),
    },
    {
      key: "last",
      header: "Last",
      secondary: true,
      render: (row) =>
        row.last_fire_at ? formatRelative(row.last_fire_at) : <span className="muted">—</span>,
    },
    {
      key: "status",
      header: "Status",
      render: (row) => (
        <div className="stack stack--tight">
          <ScheduleStatusBadge status={row.status} />
          {/* It pins its revision on purpose. Saying so is what stops it
              falling quietly behind a re-published entry. */}
          {row.revision_is_current ? null : (
            <span className="muted">running version {row.version}</span>
          )}
        </div>
      ),
    },
  ];

  return (
    <div className="stack">
      <header className="page-header">
        <div>
          <h1>Schedules</h1>
          <p className="muted">
            A catalog entry, filled in once, started on a clock. Every window becomes an
            ordinary run.
          </p>
        </div>
        <Link href="/schedules/new" className="button button--primary">
          New schedule
        </Link>
      </header>

      {query.isPending ? <Loading what="schedules" /> : null}
      {query.isError ? (
        <Failure error={query.error} onRetry={() => void query.refetch()} />
      ) : null}

      {query.data ? (
        query.data.items.length === 0 ? (
          <Empty
            title="Nothing is scheduled."
            detail="Pick a catalog entry, fill in its form once, and say how often it should run."
            action={
              <Link href="/schedules/new" className="button button--primary">
                New schedule
              </Link>
            }
          />
        ) : (
          <DataTable
            caption="Schedules"
            rows={query.data.items}
            columns={columns}
            rowKey={(row) => row.id}
            onOpen={(row) => router.push(`/schedules/${row.id}`)}
          />
        )
      ) : null}
    </div>
  );
}
