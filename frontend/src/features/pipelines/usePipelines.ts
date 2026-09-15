"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useApi } from "@/features/auth/session";
import { pipelines, runs } from "@/lib/api";
import { keys } from "@/lib/query-client";

export function usePipelineList(cursor?: string) {
  const client = useApi();
  return useQuery({
    queryKey: keys.pipelines(cursor),
    queryFn: () => pipelines.list(client, cursor ? { cursor } : {}),
  });
}

export function usePipelineRevisions(pipelineId: string) {
  const client = useApi();
  return useQuery({
    queryKey: keys.pipelineRevisions(pipelineId),
    queryFn: () => pipelines.revisions(client, pipelineId),
  });
}

/**
 * Compile without storing.
 *
 * A mutation rather than a query even though it changes nothing on the server:
 * it must fire when the author asks, not when a cache decides a document is
 * stale, and compiling a half-typed document on every keystroke would be both
 * noisy and expensive.
 */
export function useCompilePreview() {
  const client = useApi();
  return useMutation({
    mutationFn: (sourceText: string) => pipelines.compilePreview(client, sourceText),
  });
}

export function useCreateRevision() {
  const client = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { sourceText: string; title?: string }) =>
      pipelines.createRevision(client, input.sourceText, input.title),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["pipelines"] });
      void queryClient.invalidateQueries({ queryKey: ["pipeline-revisions"] });
    },
  });
}

export function useSubmitRun() {
  const client = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      revisionId: string;
      values: Record<string, unknown>;
      idempotencyKey: string;
    }) => runs.submit(client, input.revisionId, input.values, input.idempotencyKey),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["runs"] });
    },
  });
}
