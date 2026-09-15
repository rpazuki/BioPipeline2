/**
 * One badge, one vocabulary.
 *
 * The maps below are `Record<Union, Tone>`, not lookups with a fallback. A
 * status added to the backend fails this file's typecheck, which is the whole
 * reason the API schemas publish enumerations instead of `str`: the
 * alternative is a grey badge saying `retry_wait` that nobody ever notices is
 * unstyled.
 */

import type { DeliveryStatus, RunStatus, TaskStatus } from "@/lib/api";

type Tone = "neutral" | "running" | "good" | "bad" | "warn";

const RUN_TONE: Record<RunStatus, Tone> = {
  queued: "neutral",
  running: "running",
  blocked: "warn",
  cancel_requested: "warn",
  succeeded: "good",
  failed: "bad",
  cancelled: "neutral",
};

const TASK_TONE: Record<TaskStatus, Tone> = {
  created: "neutral",
  queued: "neutral",
  claimed: "running",
  running: "running",
  retry_wait: "warn",
  succeeded: "good",
  failed: "bad",
  cancelled: "neutral",
  skipped: "neutral",
};

const DELIVERY_TONE: Record<DeliveryStatus, Tone> = {
  pending: "warn",
  delivered: "good",
  failed: "bad",
  skipped: "neutral",
};

/** `cancel_requested` reads badly in a table; `retry_wait` reads as a typo. */
const WORDS: Partial<Record<string, string>> = {
  cancel_requested: "cancelling",
  retry_wait: "waiting to retry",
};

function label(status: string): string {
  return WORDS[status] ?? status.replace(/_/g, " ");
}

function Badge({ tone, status }: { tone: Tone; status: string }) {
  return (
    <span className={`badge badge--${tone}`} data-status={status}>
      {label(status)}
    </span>
  );
}

export function RunStatusBadge({ status }: { status: RunStatus }) {
  return <Badge tone={RUN_TONE[status]} status={status} />;
}

export function TaskStatusBadge({ status }: { status: TaskStatus }) {
  return <Badge tone={TASK_TONE[status]} status={status} />;
}

export function DeliveryStatusBadge({ status }: { status: DeliveryStatus }) {
  return <Badge tone={DELIVERY_TONE[status]} status={status} />;
}
