/**
 * Loading, empty, and failed — as components, so every screen fails the same
 * way.
 *
 * An empty state carries the action that would fill it. "No runs yet" with no
 * way to start one is a dead end, and the researcher's next move is to ask
 * somebody.
 */

import type { ReactNode } from "react";

import { ApiError } from "@/lib/errors";

export function Loading({ what }: { what: string }) {
  return (
    <div className="state" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      <span>Loading {what}…</span>
    </div>
  );
}

export function Empty({
  title,
  detail,
  action,
}: {
  title: string;
  detail?: string;
  action?: ReactNode;
}) {
  return (
    <div className="state state--empty">
      <p className="state__title">{title}</p>
      {detail ? <p className="muted">{detail}</p> : null}
      {action}
    </div>
  );
}

/**
 * A failure the user can act on.
 *
 * The request id is shown, not hidden in a console: it is the only thing that
 * ties "it broke at about eleven" to the log line that has the traceback, and
 * the person who can read that log is not the person looking at the screen.
 */
export function Failure({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const api = error instanceof ApiError ? error : null;
  const message =
    api?.message ?? (error instanceof Error ? error.message : "Something failed.");
  return (
    <div className="state state--failed" role="alert">
      <p className="state__title">{message}</p>
      {api?.requestId ? (
        <p className="muted">
          Reference <code>{api.requestId}</code>
        </p>
      ) : null}
      {onRetry ? (
        <button type="button" className="button" onClick={onRetry}>
          Try again
        </button>
      ) : null}
    </div>
  );
}
