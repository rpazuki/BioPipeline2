import "@/test/next-navigation";

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TasksPanel } from "@/features/runs/components/TasksPanel";
import { ADMIN, renderWithSession, stubFetch, type Route } from "@/test/render";

const RUN_ID = "00000000-0000-4000-8000-0000000000f1";
const TASK_ID = "00000000-0000-4000-8000-0000000000b1";
const LOG_ARTIFACT = "00000000-0000-4000-8000-0000000000c9";

afterEach(() => vi.unstubAllGlobals());

function task(overrides: Record<string, unknown> = {}) {
  return {
    id: TASK_ID,
    task_key: "fit:plate_01",
    stage_key: "fit",
    status: "failed",
    status_reason: "The task container exited with code 1.",
    task_class: "standard",
    attempt_count: 1,
    started_at: "2026-09-01T09:00:00Z",
    finished_at: "2026-09-01T09:04:00Z",
    ...overrides,
  };
}

const TASKS = (items: unknown[]): Route => ({
  path: `/runs/${RUN_ID}/tasks`,
  body: { items },
});

const ATTEMPTS = (items: unknown[]): Route => ({
  path: `/runs/${RUN_ID}/tasks/${TASK_ID}/attempts`,
  body: { items },
});

const LOG = (body: Record<string, unknown>): Route => ({
  path: `/runs/${RUN_ID}/tasks/${TASK_ID}/log`,
  body: {
    attempt_number: 1,
    text: "",
    bytes_read: 0,
    bytes_total: 0,
    truncated: false,
    live: false,
    artifact_id: null,
    message: null,
    ...body,
  },
});

// Order matters: the stub takes the first path that matches as a substring.
const routes = (...extra: Route[]) => [...extra, TASKS([task()])];

describe("a task's log", () => {
  it("shows what the task printed", async () => {
    stubFetch(
      routes(
        ATTEMPTS([]),
        LOG({ text: "loading plate_01\nTraceback: it went wrong\n", bytes_total: 40 }),
      ),
    );
    const user = userEvent.setup();
    renderWithSession(<TasksPanel runId={RUN_ID} live={false} />, { user: ADMIN });

    await user.click(await screen.findByRole("button", { name: "Log" }));
    expect(await screen.findByLabelText("Task log")).toHaveTextContent(
      "Traceback: it went wrong",
    );
  });

  it("says it is showing the tail, and where the rest is", async () => {
    stubFetch(
      routes(
        ATTEMPTS([]),
        LOG({
          text: "…the end\n",
          bytes_read: 65_536,
          bytes_total: 10_485_760,
          truncated: true,
          artifact_id: LOG_ARTIFACT,
        }),
      ),
    );
    const user = userEvent.setup();
    renderWithSession(<TasksPanel runId={RUN_ID} live={false} />, { user: ADMIN });

    await user.click(await screen.findByRole("button", { name: "Log" }));
    expect(await screen.findByText(/showing the last 64 kB of 10 MB/)).toBeInTheDocument();
    const download = screen.getByRole("link", { name: "Download the whole log" });
    expect(download).toHaveAttribute(
      "href",
      expect.stringContaining(`/artifacts/${LOG_ARTIFACT}/download`),
    );
  });

  it("says when a running task's log is still being written", async () => {
    // Which is also what tells the client to keep asking.
    stubFetch(routes(ATTEMPTS([]), LOG({ text: "plate 1 of 12\n", live: true })));
    const user = userEvent.setup();
    renderWithSession(<TasksPanel runId={RUN_ID} live={true} />, { user: ADMIN });

    await user.click(await screen.findByRole("button", { name: "Log" }));
    expect(await screen.findByText("still running")).toBeInTheDocument();
    expect(screen.getByText(/Updated every few seconds/)).toBeInTheDocument();
  });

  it("passes on the reason there is nothing to show", async () => {
    stubFetch(routes(ATTEMPTS([]), LOG({ message: "This attempt produced no output." })));
    const user = userEvent.setup();
    renderWithSession(<TasksPanel runId={RUN_ID} live={false} />, { user: ADMIN });

    await user.click(await screen.findByRole("button", { name: "Log" }));
    expect(await screen.findByText("This attempt produced no output.")).toBeInTheDocument();
    expect(screen.queryByLabelText("Task log")).not.toBeInTheDocument();
  });

  it("offers each attempt when a task was retried", async () => {
    // The first failure is the evidence for why there was a retry.
    stubFetch(
      routes(
        ATTEMPTS([
          { id: "a2", attempt_number: 2, status: "failed", exit_code: 1, image_ref: "img" },
          { id: "a1", attempt_number: 1, status: "lost", exit_code: null, image_ref: "img" },
        ]),
        LOG({ text: "second try\n", attempt_number: 2 }),
      ),
    );
    const user = userEvent.setup();
    renderWithSession(<TasksPanel runId={RUN_ID} live={false} />, { user: ADMIN });

    await user.click(await screen.findByRole("button", { name: "Log" }));
    expect(
      await screen.findByRole("button", { name: "Attempt 2 (exit 1)" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Attempt 1" })).toBeInTheDocument();
  });

  it("says plainly when a task has not run yet", async () => {
    // Asked of the server rather than inferred from `attempt_count`, which a
    // different function maintains — and a 404 rendered as a scary failure
    // for an ordinary state is worse than a sentence.
    stubFetch([
      {
        path: `/runs/${RUN_ID}/tasks/${TASK_ID}/log`,
        status: 404,
        body: {
          error: { code: "task.no_attempt", message: "not attempted", details: {} },
        },
      },
      ATTEMPTS([]),
      TASKS([task({ status: "queued", attempt_count: 0, started_at: null })]),
    ]);
    const user = userEvent.setup();
    renderWithSession(<TasksPanel runId={RUN_ID} live={true} />, { user: ADMIN });
    await user.click(await screen.findByRole("button", { name: "Log" }));
    expect(await screen.findByText(/has not run yet/)).toBeInTheDocument();
  });
});
