"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useApi } from "@/features/auth/session";
import { catalogApi } from "@/lib/api";
import { keys } from "@/lib/query-client";

export function useCatalog(search: string) {
  const client = useApi();
  return useQuery({
    queryKey: keys.catalog(search),
    queryFn: () => catalogApi.list(client, search || undefined),
    // A catalog changes when an admin publishes, which is rare; there is no
    // reason to re-read it on every focus.
    staleTime: 60_000,
  });
}

export function useCatalogEntry(slug: string) {
  const client = useApi();
  return useQuery({
    queryKey: keys.catalogEntry(slug),
    queryFn: () => catalogApi.get(client, slug),
    staleTime: 60_000,
  });
}

export function useSubmitFromCatalog(slug: string) {
  const client = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { values: Record<string, unknown>; idempotencyKey: string }) =>
      catalogApi.submit(client, slug, input.values, input.idempotencyKey),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["runs"] });
    },
  });
}
