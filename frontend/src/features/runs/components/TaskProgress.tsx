/**
 * Where a run has got to, counted by task.
 *
 * A bar rather than a number because the useful question during a six-hour
 * fan-out is "how much is left", and `47/163` answers it worse than a shape
 * does. The counts are also given as text, since a bar alone is unreadable to
 * a screen reader and unquantifiable to everyone else.
 */

import type { TaskStatus } from "@/lib/api";

const ORDER: TaskStatus[] = [
  "succeeded",
  "running",
  "claimed",
  "retry_wait",
  "queued",
  "created",
  "failed",
  "cancelled",
  "skipped",
];

export function TaskProgress({
  counts,
  total,
}: {
  counts: Partial<Record<TaskStatus, number>>;
  total: number;
}) {
  if (total === 0) return null;
  const present = ORDER.filter((status) => (counts[status] ?? 0) > 0);

  return (
    <div className="progress">
      <div
        className="progress__bar"
        role="img"
        aria-label={present
          .map((status) => `${counts[status]} ${status.replace(/_/g, " ")}`)
          .join(", ")}
      >
        {present.map((status) => (
          <span
            key={status}
            className={`progress__slice progress__slice--${status}`}
            style={{ width: `${((counts[status] ?? 0) / total) * 100}%` }}
          />
        ))}
      </div>
      <p className="muted">
        {present.map((status) => `${counts[status]} ${status.replace(/_/g, " ")}`).join(" · ")}
        {` · ${total} task${total === 1 ? "" : "s"}`}
      </p>
    </div>
  );
}
