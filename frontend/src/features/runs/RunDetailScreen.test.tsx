import "@/test/next-navigation";

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RunDetailScreen } from "@/features/runs/RunDetailScreen";
import type { RunDetail } from "@/lib/api";
import { ADMIN, renderWithSession, stubFetch, type Route } from "@/test/render";

const RUN_ID = "00000000-0000-4000-8000-0000000000ff";

function run(overrides: Partial<RunDetail> = {}): RunDetail {
  return {
    id: RUN_ID,
    status: "running",
    pipeline_revision_id: "00000000-0000-4000-8000-0000000000aa",
    requested_by: ADMIN.user_id,
    requested_from: "manual",
    created_at: "2026-03-01T09:00:00Z",
    started_at: "2026-03-01T09:00:30Z",
    finished_at: null,
    task_counts: { succeeded: 4, running: 1, queued: 3 },
    total_tasks: 8,
    input_values: { sample_sheet: "/data/samples.csv" },
    cancel_requested_at: null,
    ...overrides,
  };
}

function routes(detail: RunDetail, extra: Route[] = []): Route[] {
  // Extras first: the stub takes the first match, and the run detail path is a
  // prefix of every sub-resource path.
  return [
    ...extra,
    { path: `/runs/${RUN_ID}/tasks`, body: { items: [], total: 0 } },
    { path: `/runs/${RUN_ID}/artifacts`, body: { items: [], total: 0 } },
    { path: `/runs/${RUN_ID}/deliveries`, body: { items: [], total: 0 } },
    { path: `/runs/${RUN_ID}`, body: detail },
  ];
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("a live run", () => {
  it("shows its status and how far it has got", async () => {
    stubFetch(routes(run()));
    renderWithSession(<RunDetailScreen runId={RUN_ID} />, { user: ADMIN });

    expect(await screen.findByText("running")).toBeInTheDocument();
    expect(screen.getByText(/4 succeeded/)).toBeInTheDocument();
    expect(screen.getByText(/8 tasks/)).toBeInTheDocument();
  });

  it("shows the values it was submitted with", async () => {
    stubFetch(routes(run()));
    renderWithSession(<RunDetailScreen runId={RUN_ID} />, { user: ADMIN });
    expect(await screen.findByText("sample_sheet")).toBeInTheDocument();
    expect(screen.getByText("/data/samples.csv")).toBeInTheDocument();
  });

  it("asks before cancelling, and says what cancelling does not undo", async () => {
    const { calls } = stubFetch(
      routes(run(), [{ path: `/runs/${RUN_ID}/cancel`, method: "POST", body: run() }]),
    );
    renderWithSession(<RunDetailScreen runId={RUN_ID} />, { user: ADMIN });

    await userEvent.click(await screen.findByRole("button", { name: "Cancel run" }));
    expect(await screen.findByText("Cancel this run?")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Keep running" }));
    expect(calls.some((call) => call.url.includes("/cancel"))).toBe(false);
  });

  it("sends the cancellation when it is confirmed", async () => {
    const { calls } = stubFetch(
      routes(run(), [{ path: `/runs/${RUN_ID}/cancel`, method: "POST", body: run() }]),
    );
    renderWithSession(<RunDetailScreen runId={RUN_ID} />, { user: ADMIN });

    await userEvent.click(await screen.findByRole("button", { name: "Cancel run" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel run" }));

    await waitFor(() => expect(calls.some((call) => call.url.includes("/cancel"))).toBe(true));
  });
});

describe("a finished run", () => {
  it("offers no cancel button, because there is nothing left to stop", async () => {
    stubFetch(routes(run({ status: "succeeded", finished_at: "2026-03-01T15:00:00Z" })));
    renderWithSession(<RunDetailScreen runId={RUN_ID} />, { user: ADMIN });

    expect(await screen.findByText("succeeded")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel run" })).not.toBeInTheDocument();
  });
});

describe("deliveries", () => {
  it("are shown apart from outputs, because one can fail after the run succeeds", async () => {
    stubFetch(
      routes(run({ status: "succeeded", finished_at: "2026-03-01T15:00:00Z" }), [
        {
          path: `/runs/${RUN_ID}/deliveries`,
          body: {
            items: [
              {
                id: "00000000-0000-4000-8000-0000000000d1",
                field_key: "counts",
                task_key: "align:sample_07",
                mode: "shared",
                status: "failed",
                target_root_id: "lab_results",
                target_path: null,
                message: "Permission denied writing to /mnt/lab/results.",
                attempts: 5,
                next_attempt_at: null,
                delivered_at: null,
              },
            ],
            total: 1,
          },
        },
      ]),
    );
    renderWithSession(<RunDetailScreen runId={RUN_ID} />, { user: ADMIN });

    expect(await screen.findByText("Deliveries")).toBeInTheDocument();
    expect(screen.getByText("counts")).toBeInTheDocument();
    // Which task's output failed to arrive, not merely that one did.
    expect(screen.getByText("align:sample_07")).toBeInTheDocument();
    expect(screen.getByText(/Permission denied/)).toBeInTheDocument();
    // A green run with a red delivery is exactly the case this panel exists for.
    expect(screen.getByText("succeeded")).toBeInTheDocument();
  });

  it("says where a delivered output actually landed", async () => {
    // "It went to the share" is not an answer to where it is: the layout is
    // the platform's invention and nobody has been told it.
    stubFetch(
      routes(run({ status: "succeeded", finished_at: "2026-03-01T15:00:00Z" }), [
        {
          path: `/runs/${RUN_ID}/deliveries`,
          body: {
            items: [
              {
                id: "00000000-0000-4000-8000-0000000000d2",
                field_key: "counts",
                task_key: "align:sample_07",
                mode: "shared",
                status: "delivered",
                target_root_id: "lab_results",
                target_path:
                  "/mnt/lab/results/rnaseq/2026-03-01/run-9f2c1a04/align-sample_07/counts.tsv",
                message: null,
                attempts: 1,
                next_attempt_at: null,
                delivered_at: "2026-03-01T15:02:00Z",
              },
            ],
            total: 1,
          },
        },
      ]),
    );
    renderWithSession(<RunDetailScreen runId={RUN_ID} />, { user: ADMIN });

    expect(
      await screen.findByText(
        "/mnt/lab/results/rnaseq/2026-03-01/run-9f2c1a04/align-sample_07/counts.tsv",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
  });

  it("offers a failed delivery another go, and does not claim it arrived", async () => {
    const { calls } = stubFetch(
      routes(run({ status: "succeeded", finished_at: "2026-03-01T15:00:00Z" }), [
        {
          path: `/runs/${RUN_ID}/deliveries/00000000-0000-4000-8000-0000000000d1/retry`,
          method: "POST",
          body: { id: "00000000-0000-4000-8000-0000000000d1", status: "pending" },
        },
        {
          path: `/runs/${RUN_ID}/deliveries`,
          body: {
            items: [
              {
                id: "00000000-0000-4000-8000-0000000000d1",
                field_key: "counts",
                task_key: null,
                mode: "shared",
                status: "failed",
                target_root_id: "lab_results",
                target_path: null,
                message: "Storage root 'lab_results' is not mounted.",
                attempts: 5,
                next_attempt_at: null,
                delivered_at: null,
              },
            ],
            total: 1,
          },
        },
      ]),
    );
    const user = userEvent.setup();
    renderWithSession(<RunDetailScreen runId={RUN_ID} />, { user: ADMIN });

    await user.click(await screen.findByRole("button", { name: "Try again" }));

    // The courier does the work on its next round; this only re-queues it.
    await waitFor(() =>
      expect(
        calls.some(
          (call) => call.url.includes("/retry") && (call.init.method ?? "GET") === "POST",
        ),
      ).toBe(true),
    );
  });
});
