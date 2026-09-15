"use client";

/**
 * The signed-in user, and the client every screen talks to.
 *
 * Session expiry is the part worth reading. The obvious implementation — 401,
 * redirect to the login page — throws away whatever the user was doing, and
 * the thing they are most often doing here is filling in a submission form
 * with values that took real effort to assemble. So a 401 raises a flag
 * instead: the page stays exactly where it is, and a dialog asks them to sign
 * in again over the top of it. Their work is still there afterwards.
 */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { auth, type SessionResponse, type UserRole } from "@/lib/api";
import { ApiClient, onSessionExpired } from "@/lib/client";
import type { ClientConfig } from "@/lib/config";
import { ApiError } from "@/lib/errors";
import { keys } from "@/lib/query-client";

export type SessionStatus = "loading" | "authenticated" | "anonymous";

interface SessionValue {
  client: ApiClient;
  config: ClientConfig;
  user: SessionResponse | null;
  role: UserRole | undefined;
  status: SessionStatus;
  /** True only when a session existed and then stopped being accepted. */
  expired: boolean;
  signedIn: (user: SessionResponse) => void;
  signOut: () => Promise<void>;
}

const SessionContext = createContext<SessionValue | null>(null);

export function SessionProvider({
  config,
  children,
}: {
  config: ClientConfig;
  children: ReactNode;
}) {
  const queryClient = useQueryClient();
  const client = useMemo(() => new ApiClient(config), [config]);
  const [expired, setExpired] = useState(false);

  const session = useQuery({
    queryKey: keys.session,
    queryFn: ({ signal }) => auth.session(client, signal),
    // Being signed out is an answer, not a failure to retry.
    retry: (count, error) =>
      error instanceof ApiError ? error.isTransient && count < 2 : count < 2,
    staleTime: 60_000,
  });

  const user = session.data ?? null;

  useEffect(
    () =>
      onSessionExpired(() => {
        // Only a session that existed can expire. A 401 from the initial
        // session probe just means nobody is signed in.
        setExpired((was) => was || Boolean(queryClient.getQueryData(keys.session)));
      }),
    [queryClient],
  );

  const signedIn = useCallback(
    (next: SessionResponse) => {
      setExpired(false);
      queryClient.setQueryData(keys.session, next);
      // Everything read while signed out, or as somebody else, is suspect.
      void queryClient.invalidateQueries();
    },
    [queryClient],
  );

  const signOut = useCallback(async () => {
    try {
      await auth.logout(client);
    } catch {
      // The cookie may already be gone; the local state is what matters.
    }
    setExpired(false);
    queryClient.setQueryData(keys.session, null);
    queryClient.clear();
  }, [client, queryClient]);

  const status: SessionStatus = session.isPending
    ? "loading"
    : user
      ? "authenticated"
      : "anonymous";

  const value = useMemo<SessionValue>(
    () => ({
      client,
      config,
      user,
      role: user?.role,
      status,
      expired,
      signedIn,
      signOut,
    }),
    [client, config, user, status, expired, signedIn, signOut],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession must be used inside a SessionProvider");
  return value;
}

/** The API client, for screens that do not care who is signed in. */
export function useApi(): ApiClient {
  return useSession().client;
}
