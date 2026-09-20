"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useApi } from "@/features/auth/session";
import { environments } from "@/lib/api";

const keys = {
  all: () => ["environments"] as const,
  one: (id: string) => ["environment", id] as const,
  operations: (id: string) => ["environment-operations", id] as const,
  generations: (id: string) => ["environment-generations", id] as const,
  callables: (id: string, module: string) => ["environment-callables", id, module] as const,
};

export function useEnvironments() {
  const client = useApi();
  return useQuery({ queryKey: keys.all(), queryFn: () => environments.list(client) });
}

export function useEnvironment(environmentId: string | null) {
  const client = useApi();
  return useQuery({
    queryKey: keys.one(environmentId ?? ""),
    queryFn: () => environments.get(client, environmentId as string),
    enabled: Boolean(environmentId),
  });
}

export function useEnvironmentOperations(environmentId: string | null) {
  const client = useApi();
  return useQuery({
    queryKey: keys.operations(environmentId ?? ""),
    queryFn: () => environments.operations(client, environmentId as string),
    enabled: Boolean(environmentId),
  });
}

/** Every build of this environment, including the ones the janitor reclaimed. */
export function useGenerations(environmentId: string | null) {
  const client = useApi();
  return useQuery({
    queryKey: keys.generations(environmentId ?? ""),
    queryFn: () => environments.generations(client, environmentId as string),
    enabled: Boolean(environmentId),
  });
}

export function useChangePackages(environmentId: string) {
  const client = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      operation: "install" | "upgrade" | "uninstall";
      specifier: string;
    }) => environments.change(client, environmentId, input),
    // Both: the package list changed, and so did the history — including when
    // the install failed, which is the row worth reading.
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: keys.one(environmentId) });
      void queryClient.invalidateQueries({ queryKey: keys.operations(environmentId) });
      void queryClient.invalidateQueries({ queryKey: keys.generations(environmentId) });
      void queryClient.invalidateQueries({ queryKey: keys.all() });
    },
  });
}

export function useCreateEnvironment() {
  const client = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { name: string; description?: string; makeDefault?: boolean }) =>
      environments.create(client, input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: keys.all() });
    },
  });
}

export function useEnvironmentAction(environmentId: string) {
  const client = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (kind: "unlock" | "default") =>
      kind === "unlock"
        ? environments.unlock(client, environmentId)
        : environments.makeDefault(client, environmentId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: keys.all() });
      void queryClient.invalidateQueries({ queryKey: keys.one(environmentId) });
    },
  });
}

/** What an author can call. Only asked for when a module is chosen. */
export function useCallables(environmentId: string | null, module: string) {
  const client = useApi();
  return useQuery({
    queryKey: keys.callables(environmentId ?? "", module),
    queryFn: () => environments.callables(client, environmentId as string, module || undefined),
    enabled: Boolean(environmentId),
    staleTime: 60_000,
  });
}
