import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiClient, loadClientConfig, onSessionExpired } from "@/lib/client";
import type { ClientConfig } from "@/lib/config";
import { ApiError } from "@/lib/errors";

const CONFIG: ClientConfig = {
  app_name: "BioPipeline2",
  environment: "test",
  api_prefix: "/api/v1",
  base_path: "",
  upload_chunk_max_bytes: 1024,
  upload_max_total_bytes: 2048,
  csrf_header: "X-Requested-With",
  csrf_value: "BioPipeline2",
};

let fetchMock: ReturnType<typeof vi.fn>;

function reply(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
    ...init,
  });
}

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function lastCall(): [string, RequestInit] {
  const call = fetchMock.mock.calls.at(-1);
  if (!call) throw new Error("fetch was never called");
  return call as [string, RequestInit];
}

describe("request shaping", () => {
  it("sends the session cookie, which is the whole authentication scheme", async () => {
    fetchMock.mockResolvedValue(reply({ ok: true }));
    await new ApiClient(CONFIG).get("/runs");
    expect(lastCall()[1].credentials).toBe("include");
  });

  it("builds the url from what the server said, not from a baked-in prefix", async () => {
    fetchMock.mockResolvedValue(reply({}));
    await new ApiClient({ ...CONFIG, base_path: "/platform", api_prefix: "/api/v2" }).get(
      "/runs",
    );
    expect(lastCall()[0]).toBe("/platform/api/v2/runs");
  });

  it("omits empty query parameters rather than sending status=", async () => {
    fetchMock.mockResolvedValue(reply({}));
    await new ApiClient(CONFIG).get("/runs", {
      query: { status_filter: "", limit: 50, cursor: undefined },
    });
    expect(lastCall()[0]).toBe("/api/v1/runs?limit=50");
  });
});

describe("CSRF", () => {
  it("is attached to a state-changing request", async () => {
    fetchMock.mockResolvedValue(reply({}));
    await new ApiClient(CONFIG).post("/runs", { body: {} });
    const headers = lastCall()[1].headers as Record<string, string>;
    expect(headers["X-Requested-With"]).toBe("BioPipeline2");
  });

  it("is not attached to a read, which the backend does not require it on", async () => {
    fetchMock.mockResolvedValue(reply({}));
    await new ApiClient(CONFIG).get("/runs");
    const headers = lastCall()[1].headers as Record<string, string>;
    expect(headers["X-Requested-With"]).toBeUndefined();
  });

  it("uses the name the server published, not a constant compiled in here", async () => {
    fetchMock.mockResolvedValue(reply({}));
    await new ApiClient({ ...CONFIG, csrf_header: "X-Bp-Csrf", csrf_value: "sentinel" }).post(
      "/runs",
      { body: {} },
    );
    const headers = lastCall()[1].headers as Record<string, string>;
    expect(headers["X-Bp-Csrf"]).toBe("sentinel");
  });
});

describe("failures", () => {
  it("always arrive as an ApiError, never a raw Response", async () => {
    fetchMock.mockResolvedValue(
      reply({ error: { code: "run.not_found", message: "No such run." } }, { status: 404 }),
    );
    await expect(new ApiClient(CONFIG).get("/runs/x")).rejects.toBeInstanceOf(ApiError);
  });

  it("announce an expired session instead of navigating away from it", async () => {
    // A 401 mid-form must not cost the user what they had typed.
    const heard = vi.fn();
    const stop = onSessionExpired(heard);
    fetchMock.mockResolvedValue(
      reply({ error: { code: "auth.required", message: "gone" } }, { status: 401 }),
    );
    await expect(new ApiClient(CONFIG).get("/runs")).rejects.toThrow();
    expect(heard).toHaveBeenCalledOnce();
    stop();
  });

  it("report an unreachable server rather than a parse error", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(new ApiClient(CONFIG).get("/runs")).rejects.toMatchObject({
      code: "network.unreachable",
      status: 0,
    });
  });
});

describe("responses", () => {
  it("accepts 204, which logout and change-password both return", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    await expect(new ApiClient(CONFIG).post("/auth/logout")).resolves.toBeUndefined();
  });
});

describe("bootstrap", () => {
  it("reads the configuration the browser is allowed to see", async () => {
    fetchMock.mockResolvedValue(reply(CONFIG));
    await expect(loadClientConfig("/api/v1/config")).resolves.toMatchObject({
      csrf_header: "X-Requested-With",
    });
  });

  it("fails loudly when the API cannot be reached at all", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(loadClientConfig("/api/v1/config")).rejects.toBeInstanceOf(ApiError);
  });
});
