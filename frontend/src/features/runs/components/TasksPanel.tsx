"use client";

/**
 * The tasks of a run, and what each of them said.
 *
 * A task's log is opened here rather than on a page of its own: the question
 * is always "which one failed, and why", and those are one glance apart.
 */

import { useState } from "react";

import { DataTable, type Column } from "@/components/ui/DataTable";
import { TaskStatusBadge } from "@/components/ui/StatusBadge";
import { Failure, Loading } from "@/components/ui/states";
import { TaskLog } from "@/features/runs/components/TaskLog";
import { useRunTasks } from "@/features/runs/useRuns";
import type { TaskSummary } from "@/lib/api";
import { formatDuration } from "@/lib/format";

export function TasksPanel({ runId, live }: { runId: string; live: boolean }) {
  const query = useRunTasks(runId, live);
  const [opened, setOpened] = useState<TaskSummary | null>(null);

  const columns: Column<TaskSummary>[] = [
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
      key: "log",
      header: "",
      render: (task) => (
        <button
          type="button"
          className={task.status === "failed" ? "button button--primary" : "button"}
          aria-expanded={opened?.id === task.id}
          onClick={() => setOpened(opened?.id === task.id ? null : task)}
        >
          {opened?.id === task.id ? "Hide log" : "Log"}
        </button>
      ),
    },
    {
      key: "reason",
      header: "Reason",
      render: (task) => task.status_reason ?? "",
      secondary: true,
    },
  ];

  return (
    <section className="panel stack">
      <h2>Tasks</h2>
      {query.isPending ? <Loading what="tasks" /> : null}
      {query.isError ? (
        <Failure error={query.error} onRetry={() => void query.refetch()} />
      ) : null}
      {query.data ? (
        <DataTable
          caption="Tasks in this run"
          rows={query.data.items}
          columns={columns}
          rowKey={(task) => task.id}
          emptyMessage="This run has no tasks."
        />
      ) : null}
      {opened ? (
        <div className="panel panel--inset stack stack--tight">
          <h3>
            <code>{opened.task_key}</code>
          </h3>
          <TaskLog runId={runId} taskId={opened.id} />
        </div>
      ) : null}
    </section>
  );
}
