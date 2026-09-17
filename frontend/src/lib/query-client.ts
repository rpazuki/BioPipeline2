/**
 * Server state policy, in one place.
 *
 * The defaults matter more than usual here because tasks run for hours: a
 * page left open all afternoon must keep telling the truth without hammering
 * a database that is also feeding workers.
 */

import { QueryClient } from "@tanstack/react-query";

import { ApiError } from "@/lib/errors";

/**
 * How often a live run is re-read.
 *
 * There is no event stream yet, so this is polling, and the interval is
 * written down rather than guessed at each call site. Five seconds is chosen
 * against the work: nothing in this system changes state faster than a
 * container start, and a day-long alignment does not need per-second news.
 * Only non-terminal runs poll at all.
 */
export const LIVE_POLL_MS = 5_000;

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // A 401, 403, 404 or 422 will not become true by asking again, and
        // retrying a 401 three times turns one expiry into three.
        retry: (failureCount, error) =>
          error instanceof ApiError ? error.isTransient && failureCount < 2 : failureCount < 2,
        staleTime: 10_000,
        // The tab was in the background while a run finished; find out on
        // return rather than showing yesterday's status.
        refetchOnWindowFocus: true,
        refetchOnReconnect: true,
      },
      mutations: {
        // Never automatic: a retried submit is a second run.
        retry: false,
      },
    },
  });
}

/** Query keys, so an invalidation cannot miss by a typo. */
export const keys = {
  session: ["session"] as const,
  bindable: (revisionId: string) => ["bindable", revisionId] as const,
  publications: () => ["publications"] as const,
  catalog: (search: string) => ["catalog", search] as const,
  catalogEntry: (slug: string) => ["catalog-entry", slug] as const,
  runs: (filters: Record<string, unknown> = {}) => ["runs", filters] as const,
  artifact: (artifactId: string) => ["artifact", artifactId] as const,
  taskAttempts: (taskId: string) => ["task-attempts", taskId] as const,
  taskLog: (taskId: string, attempt: number | null) => ["task-log", taskId, attempt] as const,
  storageRoots: () => ["storage-roots"] as const,
  schedules: () => ["schedules"] as const,
  schedule: (scheduleId: string) => ["schedule", scheduleId] as const,
  run: (runId: string) => ["run", runId] as const,
  runTasks: (runId: string) => ["run-tasks", runId] as const,
  runArtifacts: (runId: string) => ["run-artifacts", runId] as const,
  runDeliveries: (runId: string) => ["run-deliveries", runId] as const,
  pipelines: (cursor?: string) => ["pipelines", cursor ?? null] as const,
  pipelineRevisions: (pipelineId: string) => ["pipeline-revisions", pipelineId] as const,
  revision: (revisionId: string) => ["revision", revisionId] as const,
};
