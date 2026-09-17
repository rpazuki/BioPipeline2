"use client";

/**
 * Run queries.
 *
 * The polling rule lives here rather than in a page: a run that has finished
 * must stop being polled, and a run that is live must keep being polled even
 * though nothing on screen changed for the last hour. Getting that wrong in
 * one direction wastes a database connection per open tab all afternoon, and
 * in the other shows a researcher a stale "running" for a job that failed.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useApi } from "@/features/auth/session";
import { artifacts, isTerminal, runs, type RunDetail, type RunStatus } from "@/lib/api";
import { keys, LIVE_POLL_MS } from "@/lib/query-client";

export function useRunList(status: RunStatus | "") {
  const client = useApi();
  return useQuery({
    queryKey: keys.runs({ status }),
    queryFn: () => runs.list(client, status ? { status } : {}),
    // A list is mostly other people's work finishing; a slower beat is enough.
    refetchInterval: 15_000,
  });
}

function livePoll(run: RunDetail | undefined): number | false {
  if (!run) return LIVE_POLL_MS;
  return isTerminal(run.status) ? false : LIVE_POLL_MS;
}

export function useRun(runId: string) {
  const client = useApi();
  return useQuery({
    queryKey: keys.run(runId),
    queryFn: () => runs.get(client, runId),
    refetchInterval: (query) => livePoll(query.state.data),
  });
}

export function useRunTasks(runId: string, live: boolean) {
  const client = useApi();
  return useQuery({
    queryKey: keys.runTasks(runId),
    queryFn: () => runs.tasks(client, runId),
    refetchInterval: live ? LIVE_POLL_MS : false,
  });
}

export function useRunArtifacts(runId: string, live: boolean) {
  const client = useApi();
  return useQuery({
    queryKey: keys.runArtifacts(runId),
    queryFn: () => runs.artifacts(client, runId),
    // Artifacts appear as each task finishes, so a live run keeps looking.
    refetchInterval: live ? LIVE_POLL_MS * 2 : false,
  });
}

/**
 * One artifact, for the files inside a directory of results.
 *
 * Fetched only when somebody opens it: a run can produce a dozen outputs and
 * listing every tree up front would be a manifest walk per row for something
 * nobody has asked to see.
 */
export function useArtifact(artifactId: string) {
  const client = useApi();
  return useQuery({
    queryKey: keys.artifact(artifactId),
    queryFn: () => artifacts.get(client, artifactId),
    // An artifact is immutable once promoted; only its expiry changes.
    staleTime: 5 * 60_000,
  });
}

export function useTaskAttempts(runId: string, taskId: string) {
  const client = useApi();
  return useQuery({
    queryKey: keys.taskAttempts(taskId),
    queryFn: () => runs.attempts(client, runId, taskId),
    staleTime: 10_000,
  });
}

/**
 * One task's log.
 *
 * Polls only while the *server* says the log is live — a running attempt's
 * file is still being written, and the response says so. A finished
 * attempt's log never changes, so it is never re-read.
 */
export function useTaskLog(runId: string, taskId: string, attempt: number | null) {
  const client = useApi();
  return useQuery({
    queryKey: keys.taskLog(taskId, attempt),
    queryFn: () => runs.log(client, runId, taskId, attempt ?? undefined),
    refetchInterval: (query) => (query.state.data?.live ? LIVE_POLL_MS : false),
  });
}

export function useRunDeliveries(runId: string, live: boolean) {
  const client = useApi();
  return useQuery({
    queryKey: keys.runDeliveries(runId),
    queryFn: () => runs.deliveries(client, runId),
    refetchInterval: live ? LIVE_POLL_MS * 2 : false,
  });
}

export function useCancelRun(runId: string) {
  const client = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => runs.cancel(client, runId),
    // No optimistic update: cancellation is a request, not a result. Queued
    // tasks stop at once but a running one is only flagged for its worker, and
    // showing "cancelled" before that has happened is a lie the user will
    // catch when the next poll contradicts it.
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: keys.run(runId) });
      void queryClient.invalidateQueries({ queryKey: keys.runTasks(runId) });
    },
  });
}
