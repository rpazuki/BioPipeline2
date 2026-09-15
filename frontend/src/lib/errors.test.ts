import { describe, expect, it } from "vitest";

import { ApiError, errorFromResponse, offlineError } from "@/lib/errors";

function response(
  status: number,
  body: unknown,
  headers: Record<string, string> = {},
): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

describe("the error envelope", () => {
  it("keeps the code, so a caller can branch on what went wrong", async () => {
    const error = await errorFromResponse(
      response(422, {
        error: {
          code: "pipeline.compilation_failed",
          message: "Pipeline failed to compile with 2 error(s).",
          details: { errors: [] },
          request_id: "req_abc",
        },
      }),
    );
    expect(error.code).toBe("pipeline.compilation_failed");
    expect(error.requestId).toBe("req_abc");
    expect(error.status).toBe(422);
  });

  it("survives a body that is not the envelope at all", async () => {
    // A proxy timeout returns HTML. The status is still the truth.
    const error = await errorFromResponse(new Response("<html>504</html>", { status: 504 }));
    expect(error.status).toBe(504);
    expect(error.code).toBe("http.504");
    expect(error.isTransient).toBe(true);
  });

  it("falls back to the header for a request id the envelope omitted", async () => {
    const error = await errorFromResponse(
      response(
        500,
        { error: { code: "internal.error", message: "x" } },
        {
          "X-Request-ID": "req_from_header",
        },
      ),
    );
    expect(error.requestId).toBe("req_from_header");
  });
});

describe("field problems", () => {
  it("are extracted so a form can put each on its own input", async () => {
    const error = await errorFromResponse(
      response(400, {
        error: {
          code: "request.invalid",
          message: "The request could not be understood.",
          details: {
            errors: [
              { path: "email", message: "value is not a valid email address" },
              { path: "password", message: "field required" },
            ],
          },
        },
      }),
    );
    expect(error.fieldProblems()).toEqual([
      { path: "email", message: "value is not a valid email address" },
      { path: "password", message: "field required" },
    ]);
  });

  it("are empty rather than thrown when details carries something else", () => {
    const error = new ApiError({
      status: 409,
      code: "run.conflict",
      message: "no",
      details: { errors: "not a list" },
    });
    expect(error.fieldProblems()).toEqual([]);
  });
});

describe("classification", () => {
  it("treats 4xx as final and 5xx as worth retrying", () => {
    const client = new ApiError({ status: 422, code: "x", message: "x" });
    const server = new ApiError({ status: 503, code: "x", message: "x" });
    expect(client.isTransient).toBe(false);
    expect(server.isTransient).toBe(true);
  });

  it("treats an unreachable server as transient, since it never answered", () => {
    expect(offlineError(new Error("failed to fetch")).isTransient).toBe(true);
  });
});
