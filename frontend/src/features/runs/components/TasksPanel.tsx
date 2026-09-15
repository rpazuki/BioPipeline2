"use client";

import { DataTable, type Column } from "@/components/ui/DataTable";
import { TaskStatusBadge } from "@/components/ui/StatusBadge";
import { Failure, Loading } from "@/components/ui/states";
import { useRunTasks } from "@/features/runs/useRuns";
import type { TaskSummary } from "@/lib/api";
import { formatDuration } from "@/lib/format";

const COLUMNS: Column<TaskSummary>[] = [
  {
    key: "status",
    header: "Status",
    render: (task) => <TaskStatusBadge status={task.status} />,
  },
  { key: "task", header: "Task", render: (task) => <code>{task.task_key}</code> },
  { key: "stage", header: "Stage", render: (task) => task.stage_key, secondary: true },
  { key: "class", header: "Class", render: (task) => task.task_class, secondary: true },
  {
    key: "attempts",
    header: "Attempts",
    // A task on its third attempt is the single most useful thing on this
    // page when something is wrong, so it is not a secondary column.
    render: (task) => task.attempt_count,
  },
  {
    key: "duration",
    header: "Duration",
    render: (task) => formatDuration(task.started_at, task.finished_at),
    secondary: true,
  },
  {
    key: "reason",
    header: "Reason",
    render: (task) => task.status_reason ?? "",
    secondary: true,
  },
];

export function TasksPanel({ runId, live }: { runId: string; live: boolean }) {
  const query = useRunTasks(runId, live);

  return (
    <section className="panel">
      <h2>Tasks</h2>
      {query.isPending ? <Loading what="tasks" /> : null}
      {query.isError ? (
        <Failure error={query.error} onRetry={() => void query.refetch()} />
      ) : null}
      {query.data ? (
        <DataTable
          caption="Tasks in this run"
          rows={query.data.items}
          columns={COLUMNS}
          rowKey={(task) => task.id}
          emptyMessage="This run has no tasks."
        />
      ) : null}
      <p className="muted">
        Per-attempt logs are not served by the API yet, so they are not shown here.
      </p>
    </section>
  );
}
