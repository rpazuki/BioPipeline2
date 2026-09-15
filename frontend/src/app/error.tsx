"use client";

/**
 * The page-level boundary.
 *
 * A render failure should cost one page, not the whole shell — and it must
 * offer a way out, because "something went wrong" with no button is a dead
 * end in a tab somebody has had open all afternoon.
 */

import { useEffect } from "react";

export default function PageError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="state state--failed" role="alert">
      <p className="state__title">This page failed to render.</p>
      <p className="muted">{error.message}</p>
      {error.digest ? (
        <p className="muted">
          Reference <code>{error.digest}</code>
        </p>
      ) : null}
      <button type="button" className="button" onClick={reset}>
        Try again
      </button>
    </div>
  );
}
