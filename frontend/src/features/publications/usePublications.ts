"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useApi } from "@/features/auth/session";
import { pipelines, publications, type PublicationFieldInput } from "@/lib/api";
import { keys } from "@/lib/query-client";

export function usePublications() {
  const client = useApi();
  return useQuery({
    queryKey: keys.publications(),
    queryFn: () => publications.list(client),
  });
}

export function useBindableTargets(revisionId: string | null) {
  const client = useApi();
  return useQuery({
    queryKey: keys.bindable(revisionId ?? ""),
    queryFn: () => pipelines.bindable(client, revisionId as string),
    enabled: revisionId !== null,
    // A revision is immutable, so what it offers cannot change.
    staleTime: Number.POSITIVE_INFINITY,
  });
}

export function useCreatePublication() {
  const client = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      slug: string;
      pipelineRevisionId: string;
      title: string;
      description?: string;
      fields: PublicationFieldInput[];
    }) => publications.createRevision(client, input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["publications"] });
    },
  });
}

export function usePublishRevision() {
  const client = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { publicationId: string; revisionId: string }) =>
      publications.publish(client, input.publicationId, input.revisionId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["publications"] });
      void queryClient.invalidateQueries({ queryKey: ["catalog"] });
    },
  });
}

export function useArchivePublication() {
  const client = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (publicationId: string) => publications.archive(client, publicationId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["publications"] });
      void queryClient.invalidateQueries({ queryKey: ["catalog"] });
    },
  });
}
