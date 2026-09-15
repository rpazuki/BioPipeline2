/**
 * Rendering a screen the way the application does.
 *
 * Everything below the session provider is real: the query client, the API
 * client, the error envelope handling. Only `fetch` is replaced, so a test
 * exercises the same path a browser does and a mistake in the client shows up
 * in a component test rather than in production.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderResult } from "@testing-library/react";
import type { ReactNode } from "react";
import { vi } from "vitest";

import { SessionProvider } from "@/features/auth/session";
import type { SessionResponse } from "@/lib/api";
import type { ClientConfig } from "@/lib/config";

export const TEST_CONFIG: ClientConfig = {
  app_name: "BioPipeline2",
  environment: "test",
  api_prefix: "/api/v1",
  base_path: "",
  upload_chunk_max_bytes: 1024,
  upload_max_total_bytes: 2048,
  csrf_header: "X-Requested-With",
  csrf_value: "BioPipeline2",
};

export const ADMIN: SessionResponse = {
  user_id: "00000000-0000-4000-8000-00000000000a",
  email: "admin@example.org",
  display_name: "An Admin",
  role: "admin",
};

export const RESEARCHER: SessionResponse = {
  user_id: "00000000-0000-4000-8000-00000000000b",
  email: "researcher@example.org",
  display_name: "A Researcher",
  role: "researcher",
};

export interface Route {
  /** Matched as a substring of the request URL. */
  path: string;
  status?: number;
  body?: unknown;
  method?: string;
}

/**
 * A fetch that answers from a routing table.
 *
 * Anything unrouted is a 404 with a real error envelope rather than a hang or
 * an undefined — an unexpected request should fail the test visibly.
 */
export function stubFetch(routes: Route[]) {
  const calls: { url: string; init: RequestInit }[] = [];

  const impl = vi.fn(async (url: string | URL | Request, init: RequestInit = {}) => {
    const href = String(url);
    calls.push({ url: href, init });
    const method = (init.method ?? "GET").toUpperCase();
    const route = routes.find(
      (candidate) =>
        href.includes(candidate.path) && (candidate.method ?? "GET").toUpperCase() === method,
    );
    if (!route) {
      return new Response(
        JSON.stringify({
          error: {
            code: "test.unrouted",
            message: `No stub for ${method} ${href}`,
            details: {},
          },
        }),
        { status: 404, headers: { "Content-Type": "application/json" } },
      );
    }
    const status = route.status ?? 200;
    if (status === 204) return new Response(null, { status });
    return new Response(JSON.stringify(route.body ?? {}), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  });

  vi.stubGlobal("fetch", impl);
  return { calls, impl };
}

export function renderWithSession(
  ui: ReactNode,
  options: { user?: SessionResponse | null } = {},
): RenderResult {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  if (options.user !== undefined) queryClient.setQueryData(["session"], options.user);

  return render(
    <QueryClientProvider client={queryClient}>
      <SessionProvider config={TEST_CONFIG}>{ui}</SessionProvider>
    </QueryClientProvider>,
  );
}
