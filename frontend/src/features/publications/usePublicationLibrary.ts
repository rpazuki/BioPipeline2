"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useApi } from "@/features/auth/session";

export interface PublicationLibrary {
  source_text: string;
  digest: string;
  schemas: Record<string, Record<string, unknown>>;
  presets: Record<string, { type_ref: string; value: unknown; description?: string | null }>;
}

export function usePublicationLibrary() {
  const client = useApi();
  return useQuery({
    queryKey: ["publication-library"],
    queryFn: () => client.get<PublicationLibrary>("/publication-library"),
  });
}

export function useValidateLibrary() {
  const client = useApi();
  return useMutation({
    mutationFn: (source: string) =>
      client.post<PublicationLibrary>("/publication-library/validate", {
        body: { source_text: source },
      }),
  });
}

export function useSaveLibrary() {
  const client = useApi();
  const queries = useQueryClient();
  return useMutation({
    mutationFn: (input: { source_text: string; expected_digest: string }) =>
      client.request<PublicationLibrary>("PUT", "/publication-library", { body: input }),
    onSuccess: (data) => queries.setQueryData(["publication-library"], data),
  });
}

export function useImportLibrary() {
  const client = useApi();
  return useMutation({
    mutationFn: (input: {
      source_text: string;
      base_source: string;
      expected_digest: string;
      format: "legacy_types" | "legacy_constants" | "presets";
    }) =>
      client.post<{ source_text: string; base_digest: string; notes: string[] }>(
        "/publication-library/import-preview",
        { body: input },
      ),
  });
}
