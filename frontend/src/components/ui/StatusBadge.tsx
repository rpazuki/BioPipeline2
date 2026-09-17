/**
 * One badge, one vocabulary.
 *
 * The maps below are `Record<Union, Tone>`, not lookups with a fallback. A
 * status added to the backend fails this file's typecheck, which is the whole
 * reason the API schemas publish enumerations instead of `str`: the
 * alternative is a grey badge saying `retry_wait` that nobody ever notices is
 * unstyled.
 */

import type {
  DeliveryStatus,
  FireOutcome,
  RunStatus,
  ScheduleStatus,
  TaskStatus,
} from "@/lib/api";

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

const SCHEDULE_TONE: Record<ScheduleStatus, Tone> = {
  active: "good",
  paused: "warn",
  archived: "neutral",
};

const FIRE_TONE: Record<FireOutcome, Tone> = {
  created: "good",
  skipped_overlap: "warn",
  skipped_catchup: "warn",
  failed: "bad",
};

/** `cancel_requested` reads badly in a table; `retry_wait` reads as a typo. */
const WORDS: Partial<Record<string, string>> = {
  cancel_requested: "cancelling",
  retry_wait: "waiting to retry",
};

/**
 * A fire outcome's words, kept apart from the rest.
 *
 * `created` means opposite things in the two vocabularies: a window that
 * produced a run, and a task that has not started. One shared map would have
 * rendered an unstarted task as "ran".
 */
const FIRE_WORDS: Record<FireOutcome, string> = {
  created: "ran",
  skipped_overlap: "skipped, already running",
  skipped_catchup: "skipped, missed",
  failed: "failed",
};

function Badge({ tone, status, text }: { tone: Tone; status: string; text?: string }) {
  return (
    <span className={`badge badge--${tone}`} data-status={status}>
      {text ?? WORDS[status] ?? status.replace(/_/g, " ")}
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

export function ScheduleStatusBadge({ status }: { status: ScheduleStatus }) {
  return <Badge tone={SCHEDULE_TONE[status]} status={status} />;
}

export function FireOutcomeBadge({ outcome }: { outcome: FireOutcome }) {
  return <Badge tone={FIRE_TONE[outcome]} status={outcome} text={FIRE_WORDS[outcome]} />;
}
