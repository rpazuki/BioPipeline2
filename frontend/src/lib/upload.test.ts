/**
 * The transfer, and the three ways it goes wrong.
 *
 * A chunked upload is easy to write and easy to get subtly wrong: an offset
 * kept on the client that drifts, a retry that starts from zero, a failure
 * that loses the whole file. Each of those is a test here.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiClient } from "@/lib/client";
import type { ClientConfig } from "@/lib/config";
import { CHUNK_CEILING, chunkSize, uploadFile } from "@/lib/upload";

const CONFIG: ClientConfig = {
  app_name: "BioPipeline2",
  environment: "test",
  api_prefix: "/api/v1",
  base_path: "",
  upload_chunk_max_bytes: 4,
  upload_max_total_bytes: 2048,
  csrf_header: "X-Requested-With",
  csrf_value: "BioPipeline2",
};

const UPLOAD_ID = "00000000-0000-4000-8000-0000000000e1";

let fetchMock: ReturnType<typeof vi.fn>;

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function upload(overrides: Record<string, unknown> = {}) {
  return {
    id: UPLOAD_ID,
    filename: "plate.csv",
    status: "open",
    received_bytes: 0,
    declared_size_bytes: 12,
    chunk_max_bytes: 4,
    expires_at: "2026-09-20T00:00:00Z",
    reference: null,
    ...overrides,
  };
}

function conflict(expected: number, status = 409): Response {
  return json(
    {
      error: {
        code: "upload.offset_conflict",
        message: "wrong place",
        details: { expected_offset: expected },
        request_id: "req_1",
      },
    },
    status,
  );
}

function aFile(text: string, name = "plate.csv"): File {
  return new File([text], name, { type: "text/csv" });
}

/** The offsets the client actually wrote at, in order. */
function ranges(): string[] {
  return fetchMock.mock.calls
    .filter(([, init]) => (init as RequestInit)?.method === "PATCH")
    .map(([, init]) => {
      const headers = (init as RequestInit).headers as Record<string, string>;
      return headers["Content-Range"] ?? "(none)";
    });
}

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => vi.unstubAllGlobals());

describe("sending a file", () => {
  it("sends it in chunks and finishes with the reference the form needs", async () => {
    let received = 0;
    fetchMock.mockImplementation(async (_url: string, init: RequestInit) => {
      if (init.method === "POST" && String(_url).endsWith("/complete")) {
        return json(upload({ status: "completed", received_bytes: 12, reference: "upload:x" }));
      }
      if (init.method === "POST") return json(upload());
      received += 4;
      return json(upload({ received_bytes: received }));
    });

    const client = new ApiClient(CONFIG);
    const progress: number[] = [];
    const finished = await uploadFile(client, aFile("123456789012"), {
      onProgress: (p) => progress.push(p.sent),
    });

    expect(ranges()).toEqual(["bytes 0-3/12", "bytes 4-7/12", "bytes 8-11/12"]);
    expect(progress).toEqual([0, 4, 8, 12]);
    expect(finished.reference).toBe("upload:x");
  });

  it("continues from where the server says, not from where it thought", async () => {
    // The case a client-side counter gets wrong: a request that died after
    // writing its bytes but before the response came back.
    let seen = 0;
    fetchMock.mockImplementation(async (url: string, init: RequestInit) => {
      if (init.method === "POST" && String(url).endsWith("/complete")) {
        return json(upload({ status: "completed", received_bytes: 12, reference: "upload:x" }));
      }
      if (init.method === "POST") return json(upload());
      seen += 1;
      if (seen === 1) return conflict(8);
      return json(upload({ received_bytes: 12 }));
    });

    const client = new ApiClient(CONFIG);
    await uploadFile(client, aFile("123456789012"));

    // Not 0-3 twice: the second attempt starts at the server's offset.
    expect(ranges()).toEqual(["bytes 0-3/12", "bytes 8-11/12"]);
  });

  it("asks where it got to after a dropped connection rather than starting again", async () => {
    let patches = 0;
    fetchMock.mockImplementation(async (url: string, init: RequestInit) => {
      const href = String(url);
      if (init.method === "POST" && href.endsWith("/complete")) {
        return json(upload({ status: "completed", received_bytes: 12, reference: "upload:x" }));
      }
      if (init.method === "POST") return json(upload());
      if (init.method === "PATCH") {
        patches += 1;
        if (patches === 1) return json({ error: { code: "x", message: "gateway" } }, 502);
        return json(upload({ received_bytes: 12 }));
      }
      // The GET that follows the failure: most of the chunk did arrive.
      return json(upload({ received_bytes: 3 }));
    });

    const client = new ApiClient(CONFIG);
    await uploadFile(client, aFile("123456789012"));

    // The retry resumes at 3, not at 0 and not at 4: three of the four bytes
    // in the failed chunk did arrive, and only the missing one is resent.
    expect(ranges()).toEqual(["bytes 0-3/12", "bytes 3-6/12"]);
  });

  it("gives up after three failures on one chunk, keeping the upload", async () => {
    fetchMock.mockImplementation(async (url: string, init: RequestInit) => {
      if (init.method === "POST") return json(upload());
      if (init.method === "PATCH") return json({ error: { code: "x", message: "down" } }, 503);
      return json(upload({ received_bytes: 0 }));
    });

    const client = new ApiClient(CONFIG);
    await expect(uploadFile(client, aFile("123456789012"))).rejects.toThrow("down");
    // Never completed: the bytes stay on the server for a later retry rather
    // than being certified as a whole file.
    expect(
      fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/complete")),
    ).toHaveLength(0);
  });

  it("stops when the researcher stops it", async () => {
    const controller = new AbortController();
    fetchMock.mockImplementation(async (url: string, init: RequestInit) => {
      if (init.method === "POST") return json(upload());
      controller.abort();
      return json(upload({ received_bytes: 4 }));
    });

    const client = new ApiClient(CONFIG);
    await expect(
      uploadFile(client, aFile("123456789012"), { signal: controller.signal }),
    ).rejects.toThrow();
  });

  it("carries on with an upload that was already open", async () => {
    fetchMock.mockImplementation(async (url: string, init: RequestInit) => {
      if (init.method === "POST" && String(url).endsWith("/complete")) {
        return json(upload({ status: "completed", reference: "upload:x" }));
      }
      return json(upload({ received_bytes: 12 }));
    });

    const client = new ApiClient(CONFIG);
    await uploadFile(client, aFile("123456789012"), {
      resume: upload({ received_bytes: 8 }) as never,
    });

    // One chunk, not three: eight bytes were already there.
    expect(ranges()).toEqual(["bytes 8-11/12"]);
    expect(
      fetchMock.mock.calls.filter(([, init]) => (init as RequestInit).method === "POST"),
    ).toHaveLength(1);
  });
});

describe("chunk size", () => {
  it("never exceeds what the deployment accepts", () => {
    expect(chunkSize(new ApiClient(CONFIG))).toBe(4);
  });

  it("is capped well below a deployment that allows enormous chunks", () => {
    // A 64 MB chunk means a progress bar that moves twice and a failure that
    // costs all of it.
    const generous = new ApiClient({ ...CONFIG, upload_chunk_max_bytes: 64 * 1024 * 1024 });
    expect(chunkSize(generous)).toBe(CHUNK_CEILING);
  });
});
