"use client";

/**
 * One schedule: what it runs, when, and what has actually happened.
 *
 * The history is the point. A schedule is the part of the system nobody
 * watches, so the question it has to answer on sight is not "is it configured"
 * but "did it run, and if not, why not" — which is exactly what a window's
 * outcome says.
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { DataTable, type Column } from "@/components/ui/DataTable";
import { Dialog } from "@/components/ui/Dialog";
import { FireOutcomeBadge, ScheduleStatusBadge } from "@/components/ui/StatusBadge";
import { Failure, Loading } from "@/components/ui/states";
import { describe } from "@/features/schedules/recurrence";
import { useSchedule, useScheduleAction } from "@/features/schedules/useSchedules";
import type { ScheduleFire } from "@/lib/api";
import { formatRelative, formatTimestamp } from "@/lib/format";

export function ScheduleScreen({ scheduleId }: { scheduleId: string }) {
  const router = useRouter();
  const query = useSchedule(scheduleId);
  const act = useScheduleAction(scheduleId);
  const [retiring, setRetiring] = useState(false);

  if (query.isPending) return <Loading what="this schedule" />;
  if (query.isError) {
    return <Failure error={query.error} onRetry={() => void query.refetch()} />;
  }

  const schedule = query.data;
  // The contract makes these optional because each has a server-side default;
  // an absent list and an empty one mean the same thing here.
  const entryFields = schedule.fields ?? [];
  const fires = schedule.fires ?? [];
  const events = schedule.events ?? [];
  const values = schedule.values ?? {};
  const labels = new Map(entryFields.map((field) => [field.key, field.label]));

  const fireColumns: Column<ScheduleFire>[] = [
    {
      key: "window",
      header: "Window",
      // The scheduled window, not when the scheduler woke up. A late fire and
      // an on-time one are the same window.
      render: (row) => (
        <span title={formatTimestamp(row.fire_at)}>{formatRelative(row.fire_at)}</span>
      ),
    },
    {
      key: "outcome",
      header: "Outcome",
      render: (row) => <FireOutcomeBadge outcome={row.outcome} />,
    },
    {
      key: "run",
      header: "Run",
      render: (row) =>
        row.run_id ? (
          <Link href={`/runs/${row.run_id}`}>Open run</Link>
        ) : (
          <span className="muted">none</span>
        ),
    },
    { key: "why", header: "", secondary: true, render: (row) => row.message ?? "" },
  ];

  return (
    <div className="stack">
      <header className="page-header">
        <div>
          <h1>{schedule.title}</h1>
          <p className="muted">
            {describe(schedule.rrule, schedule.interval_seconds, schedule.timezone)} —{" "}
            <Link href={`/catalog/${schedule.slug}`}>{schedule.entry_title}</Link>, version{" "}
            {schedule.version}
          </p>
        </div>
        <div className="page-header__meta">
          <ScheduleStatusBadge status={schedule.status} />
        </div>
      </header>

      {schedule.revision_is_current ? null : (
        <div className="state state--empty" role="status">
          <p className="state__title">This entry has been published again since.</p>
          <p className="muted">
            The schedule keeps running version {schedule.version}, which is deliberate — nothing
            it produces changes without somebody asking. Create a new schedule to follow the
            current version.
          </p>
        </div>
      )}

      {act.isError ? <Failure error={act.error} /> : null}

      <section className="panel stack">
        <h2>Next</h2>
        <dl className="detail-list">
          <div className="detail-list__pair">
            <dt>Next window</dt>
            <dd>
              {schedule.next_fire_at ? (
                formatTimestamp(schedule.next_fire_at)
              ) : (
                <span className="muted">
                  {schedule.status === "active"
                    ? "never again — the recurrence has run out"
                    : "nothing while it is not active"}
                </span>
              )}
            </dd>
          </div>
          <div className="detail-list__pair">
            <dt>Last window</dt>
            <dd>
              {schedule.last_fire_at ? (
                formatTimestamp(schedule.last_fire_at)
              ) : (
                <span className="muted">it has not fired yet</span>
              )}
            </dd>
          </div>
          <div className="detail-list__pair">
            <dt>If one is still running</dt>
            <dd>{schedule.overlap_policy.replace(/_/g, " ")}</dd>
          </div>
          <div className="detail-list__pair">
            <dt>After an outage</dt>
            <dd>{schedule.catchup_policy.replace(/_/g, " ")}</dd>
          </div>
        </dl>

        <div className="button-row">
          {schedule.status === "active" ? (
            <button
              type="button"
              className="button"
              disabled={act.isPending}
              onClick={() => act.mutate("pause")}
            >
              Pause
            </button>
          ) : null}
          {schedule.status === "paused" ? (
            <button
              type="button"
              className="button button--primary"
              disabled={act.isPending}
              onClick={() => act.mutate("resume")}
            >
              Resume
            </button>
          ) : null}
          {schedule.status === "archived" ? null : (
            <button type="button" className="button" onClick={() => setRetiring(true)}>
              Retire
            </button>
          )}
        </div>
        {schedule.status === "paused" ? (
          <p className="muted">
            Resuming starts from the next window. Whatever was owed while it was paused is
            dropped — a fortnight paused should not answer with a fortnight of runs.
          </p>
        ) : null}
      </section>

      <section className="panel stack">
        <h2>Values</h2>
        {Object.keys(values).length === 0 ? (
          <p className="muted">This entry takes no values.</p>
        ) : (
          <dl className="detail-list">
            {Object.entries(values).map(([key, value]) => (
              <div key={key} className="detail-list__pair">
                {/* The admin's words where they exist; the raw key only if the
                    entry no longer has that field. */}
                <dt>{labels.get(key) ?? key}</dt>
                <dd>
                  <code>{JSON.stringify(value)}</code>
                </dd>
              </div>
            ))}
          </dl>
        )}
      </section>

      <section className="panel stack">
        <h2>Windows</h2>
        <DataTable
          caption="Recent windows"
          rows={fires}
          columns={fireColumns}
          rowKey={(row) => row.fire_at}
          emptyMessage="No window has come round yet."
        />
      </section>

      <section className="panel stack">
        <h2>History</h2>
        {events.length === 0 ? (
          <p className="muted">Nothing recorded.</p>
        ) : (
          <ul className="timeline">
            {events.map((event) => (
              <li key={`${event.created_at}-${event.event_type}`}>
                <strong>{event.event_type.replace(/_/g, " ")}</strong>{" "}
                <span className="muted">{formatRelative(event.created_at)}</span>
                {event.message ? <p className="muted">{event.message}</p> : null}
              </li>
            ))}
          </ul>
        )}
      </section>

      <Dialog open={retiring} title="Retire this schedule?" onClose={() => setRetiring(false)}>
        <p>
          It stops firing. Its history and the runs it started stay — this removes it from the
          things that will happen, not from the record of what did.
        </p>
        <div className="dialog__actions">
          <button
            type="button"
            className="button button--quiet"
            onClick={() => setRetiring(false)}
          >
            Keep it
          </button>
          <button
            type="button"
            className="button button--primary"
            disabled={act.isPending}
            onClick={() =>
              act.mutate("archive", {
                onSuccess: () => {
                  setRetiring(false);
                  router.push("/schedules");
                },
              })
            }
          >
            Retire
          </button>
        </div>
      </Dialog>
    </div>
  );
}
