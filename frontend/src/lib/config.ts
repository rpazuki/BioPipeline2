/**
 * Where the API is, and what the server says about itself.
 *
 * Two layers, deliberately:
 *
 * - **Build-time**, and only what cannot be anything else: the origin (the
 *   frontend and the API share one in production but not in development) and
 *   the path prefix (Next bakes it into every asset URL).
 * - **Runtime**, everything else, from `GET {prefix}/config`. One build then
 *   serves several deployments without a rebuild, which is what
 *   `Settings.public()` on the backend exists for.
 *
 * `DEFAULT_API_PREFIX` is the single place a version prefix is written down in
 * this codebase. It is a *bootstrap guess*: the server answers with its own
 * `api_prefix` and `base_path`, and every later request uses those. A
 * deployment that moves the API only has to stay reachable at the guess long
 * enough to answer once.
 */

import type { components } from "@/generated/api-types";

export type ClientConfig = components["schemas"]["ClientConfigResponse"];

export const DEFAULT_API_PREFIX = "/api/v1";

function env(name: string): string {
  // Next inlines `process.env.NEXT_PUBLIC_*` at build time, so these cannot be
  // read from a variable key.
  switch (name) {
    case "NEXT_PUBLIC_API_ORIGIN":
      return process.env.NEXT_PUBLIC_API_ORIGIN ?? "";
    case "NEXT_PUBLIC_API_PREFIX":
      return process.env.NEXT_PUBLIC_API_PREFIX ?? "";
    case "NEXT_PUBLIC_BASE_PATH":
      return process.env.NEXT_PUBLIC_BASE_PATH ?? "";
    default:
      return "";
  }
}

/** Empty means same-origin, which is the production shape. */
export function apiOrigin(): string {
  return env("NEXT_PUBLIC_API_ORIGIN").replace(/\/$/, "");
}

export function buildTimeBasePath(): string {
  return env("NEXT_PUBLIC_BASE_PATH").replace(/\/$/, "");
}

/** The URL the client boots from, before the server has told us anything. */
export function bootstrapUrl(): string {
  const prefix = env("NEXT_PUBLIC_API_PREFIX") || DEFAULT_API_PREFIX;
  return `${apiOrigin()}${buildTimeBasePath()}${prefix}/config`;
}

/** Where every other request goes, once the server has answered. */
export function apiRoot(config: ClientConfig): string {
  return `${apiOrigin()}${config.base_path}${config.api_prefix}`;
}
