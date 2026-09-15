/**
 * The backend's error envelope, as something a component can branch on.
 *
 * Every failure arrives as
 * `{"error": {"code", "message", "details", "request_id"}}`, so this is the
 * one place that shape is understood. Components see a typed `ApiError` with a
 * stable `code`, never a parsed body.
 */

export interface FieldProblem {
  path: string;
  message: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;
  readonly requestId: string;

  constructor(init: {
    status: number;
    code: string;
    message: string;
    details?: Record<string, unknown>;
    requestId?: string;
  }) {
    super(init.message);
    this.name = "ApiError";
    this.status = init.status;
    this.code = init.code;
    this.details = init.details ?? {};
    this.requestId = init.requestId ?? "";
  }

  /** True when re-sending the same request could plausibly work. */
  get isTransient(): boolean {
    return this.status === 0 || this.status >= 500;
  }

  get isUnauthenticated(): boolean {
    return this.status === 401;
  }

  get isForbidden(): boolean {
    return this.status === 403;
  }

  get isNotFound(): boolean {
    return this.status === 404;
  }

  /**
   * Per-field problems, if the failure had any.
   *
   * Both the request-validation handler and the compiler put a list of
   * `{path, message}` under `details.errors`, which is what lets a form put a
   * message next to the input that caused it rather than in a toast the user
   * has to map back to a field themselves.
   */
  fieldProblems(): FieldProblem[] {
    const raw = this.details["errors"];
    if (!Array.isArray(raw)) return [];
    return raw.flatMap((entry) => {
      if (typeof entry !== "object" || entry === null) return [];
      const record = entry as Record<string, unknown>;
      const path = record["path"] ?? record["location"];
      const message = record["message"];
      if (typeof message !== "string") return [];
      return [{ path: typeof path === "string" ? path : "", message }];
    });
  }
}

/** Parse a failed response body into an `ApiError`. */
export async function errorFromResponse(response: Response): Promise<ApiError> {
  const requestId = response.headers.get("X-Request-ID") ?? "";
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    // A proxy timeout or a crash upstream returns HTML, or nothing at all.
    // The status is still the truth; the envelope is not guaranteed.
  }
  const envelope =
    typeof body === "object" && body !== null
      ? ((body as Record<string, unknown>)["error"] as Record<string, unknown> | undefined)
      : undefined;

  return new ApiError({
    status: response.status,
    code: typeof envelope?.["code"] === "string" ? envelope["code"] : `http.${response.status}`,
    message:
      typeof envelope?.["message"] === "string" && envelope["message"]
        ? envelope["message"]
        : response.statusText || "The request failed.",
    details:
      typeof envelope?.["details"] === "object" && envelope["details"] !== null
        ? (envelope["details"] as Record<string, unknown>)
        : {},
    requestId:
      typeof envelope?.["request_id"] === "string" ? envelope["request_id"] : requestId,
  });
}

/** A network failure, which never reaches the server and so has no envelope. */
export function offlineError(cause: unknown): ApiError {
  return new ApiError({
    status: 0,
    code: "network.unreachable",
    message:
      cause instanceof Error && cause.name === "AbortError"
        ? "The request was cancelled."
        : "Could not reach the server.",
  });
}
