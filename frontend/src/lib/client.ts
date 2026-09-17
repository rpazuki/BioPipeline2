/**
 * The HTTP client.
 *
 * Small on purpose. A generated client would have to be taught the same four
 * conventions anyway — the cookie, the CSRF header, the error envelope, the
 * request id — and the types are already generated from the committed
 * contract, which is where the real safety comes from.
 *
 * What the rest of the app never has to think about:
 *
 * - **Credentials.** The session is an httpOnly cookie, so `credentials:
 *   "include"` is mandatory and easy to forget once.
 * - **CSRF.** Cookie auth means the browser attaches the session to any
 *   request it can be induced to make. The backend requires a custom header on
 *   unsafe methods; the header's name and value come from `/config`, not from
 *   a constant duplicated here.
 * - **Errors.** Always an `ApiError`, never a raw `Response`.
 * - **Expiry.** A 401 is announced rather than redirected, so a half-filled
 *   form survives it.
 */

import { apiRoot, type ClientConfig } from "@/lib/config";
import { ApiError, errorFromResponse, offlineError } from "@/lib/errors";

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

export type QueryValue = string | number | boolean | undefined | null;

export interface RequestOptions {
  query?: Record<string, QueryValue>;
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

type Listener = () => void;

const expiryListeners = new Set<Listener>();

/**
 * Called whenever the server says the session is gone.
 *
 * Deliberately an event rather than a redirect: the session can expire while
 * somebody is halfway through a submission form, and navigating away from that
 * loses their work. The shell shows a sign-in dialog over the page instead.
 */
export function onSessionExpired(listener: Listener): () => void {
  expiryListeners.add(listener);
  return () => expiryListeners.delete(listener);
}

function announceExpiry(): void {
  for (const listener of expiryListeners) listener();
}

function queryString(query: Record<string, QueryValue> | undefined): string {
  if (!query) return "";
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") continue;
    params.set(key, String(value));
  }
  const rendered = params.toString();
  return rendered ? `?${rendered}` : "";
}

export class ApiClient {
  constructor(private readonly config: ClientConfig) {}

  get settings(): ClientConfig {
    return this.config;
  }

  async request<T>(method: string, path: string, options: RequestOptions = {}): Promise<T> {
    const url = `${apiRoot(this.config)}${path}${queryString(options.query)}`;
    const headers: Record<string, string> = { Accept: "application/json", ...options.headers };

    if (!SAFE_METHODS.has(method)) {
      headers[this.config.csrf_header] = this.config.csrf_value;
    }
    if (options.body !== undefined) {
      headers["Content-Type"] = "application/json";
    }

    let response: Response;
    try {
      response = await fetch(url, {
        method,
        headers,
        credentials: "include",
        body: options.body === undefined ? undefined : JSON.stringify(options.body),
        ...(options.signal ? { signal: options.signal } : {}),
      });
    } catch (cause) {
      throw offlineError(cause);
    }

    if (!response.ok) {
      const error = await errorFromResponse(response);
      if (error.isUnauthenticated) announceExpiry();
      throw error;
    }

    if (response.status === 204 || response.headers.get("Content-Length") === "0") {
      return undefined as T;
    }
    try {
      return (await response.json()) as T;
    } catch {
      throw new ApiError({
        status: response.status,
        code: "response.unreadable",
        message: "The server returned a response this client could not read.",
        requestId: response.headers.get("X-Request-ID") ?? "",
      });
    }
  }

  /**
   * A URL the browser can navigate to, for content this client must not fetch.
   *
   * An artifact can be tens of gigabytes. Fetching one to make a blob URL
   * would hold all of it in the tab's memory before a single byte reached the
   * disk, so a download is a plain link the browser streams itself — which
   * also gets range requests and a resumable transfer for free. The session
   * cookie rides along because a top-level GET is a safe method.
   */
  hrefFor(path: string, query?: Record<string, QueryValue>): string {
    return `${apiRoot(this.config)}${path}${queryString(query)}`;
  }

  get<T>(path: string, options?: RequestOptions): Promise<T> {
    return this.request<T>("GET", path, options);
  }

  post<T>(path: string, options?: RequestOptions): Promise<T> {
    return this.request<T>("POST", path, options);
  }
}

/** Fetch the runtime configuration the client is built around. */
export async function loadClientConfig(
  url: string,
  signal?: AbortSignal,
): Promise<ClientConfig> {
  let response: Response;
  try {
    response = await fetch(url, {
      headers: { Accept: "application/json" },
      credentials: "include",
      ...(signal ? { signal } : {}),
    });
  } catch (cause) {
    throw offlineError(cause);
  }
  if (!response.ok) throw await errorFromResponse(response);
  return (await response.json()) as ClientConfig;
}
