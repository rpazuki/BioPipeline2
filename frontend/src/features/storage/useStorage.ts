"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useApi } from "@/features/auth/session";
import { storageRoots, type NewStorageRoot } from "@/lib/api";
import { keys } from "@/lib/query-client";

export function useStorageRoots() {
  const client = useApi();
  return useQuery({
    queryKey: keys.storageRoots(),
    queryFn: () => storageRoots.list(client),
    // `visible` is a filesystem check, so a share that went away should show
    // up on a revisit rather than on a reload.
    staleTime: 15_000,
  });
}

export function useRegisterStorageRoot() {
  const client = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: NewStorageRoot) => storageRoots.register(client, input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: keys.storageRoots() });
    },
  });
}

export function useStorageRootAction() {
  const client = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { rootId: string; kind: "revoke" | "reinstate"; text: string }) =>
      input.kind === "revoke"
        ? storageRoots.revoke(client, input.rootId, input.text)
        : storageRoots.reinstate(client, input.rootId, input.text),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: keys.storageRoots() });
    },
  });
}
