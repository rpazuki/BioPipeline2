"use client";

/**
 * Nothing renders until the server has said where it is.
 *
 * The alternative — render optimistically against a baked-in prefix — fails in
 * the one case this exists for: a deployment mounted somewhere the build did
 * not predict. Better a spinner for 30ms than a screen of 404s.
 */

import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { loadClientConfig } from "@/lib/client";
import { bootstrapUrl } from "@/lib/config";
import { ApiError } from "@/lib/errors";
import { SessionProvider } from "@/features/auth/session";

export function ConfigGate({ children }: { children: ReactNode }) {
  const config = useQuery({
    queryKey: ["client-config"],
    queryFn: ({ signal }) => loadClientConfig(bootstrapUrl(), signal),
    staleTime: Number.POSITIVE_INFINITY,
    retry: 2,
  });

  if (config.isPending) {
    return (
      <div className="boot" role="status" aria-live="polite">
        <span className="spinner" aria-hidden="true" />
        <span>Starting…</span>
      </div>
    );
  }

  if (config.isError) {
    const error = config.error;
    return (
      <div className="boot boot--failed" role="alert">
        <h1>Cannot reach the server</h1>
        <p>{error instanceof ApiError ? error.message : "The application failed to start."}</p>
        <p className="muted">
          Tried <code>{bootstrapUrl()}</code>.
        </p>
        <button type="button" className="button" onClick={() => void config.refetch()}>
          Try again
        </button>
      </div>
    );
  }

  return <SessionProvider config={config.data}>{children}</SessionProvider>;
}
