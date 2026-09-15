import "@/test/next-navigation";

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RunsScreen } from "@/features/runs/RunsScreen";
import { ADMIN, renderWithSession, stubFetch } from "@/test/render";
import { router } from "@/test/next-navigation";

const RUN = {
  id: "00000000-0000-4000-8000-0000000000f1",
  status: "failed" as const,
  pipeline_revision_id: "00000000-0000-4000-8000-0000000000e1",
  requested_by: ADMIN.user_id,
  created_at: "2026-03-01T09:00:00Z",
  started_at: "2026-03-01T09:00:30Z",
  finished_at: "2026-03-01T09:04:00Z",
};

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("the run list", () => {
  it("filters by status server-side rather than hiding rows locally", async () => {
    // Filtering is why the old system needed failed runs deleted to stay
    // readable; asking the server keeps the page small as well as correct.
    const { calls } = stubFetch([{ path: "/runs", body: { items: [RUN] } }]);
    renderWithSession(<RunsScreen />, { user: ADMIN });

    await screen.findByText("failed");
    await userEvent.selectOptions(screen.getByLabelText("Filter by status"), "failed");

    await waitFor(() =>
      expect(calls.some((call) => call.url.includes("status_filter=failed"))).toBe(true),
    );
  });

  it("opens a run when its row is activated from the keyboard", async () => {
    stubFetch([{ path: "/runs", body: { items: [RUN] } }]);
    renderWithSession(<RunsScreen />, { user: ADMIN });

    const row = await screen.findByRole("link", { name: /failed/ });
    row.focus();
    await userEvent.keyboard("{Enter}");

    expect(router.push).toHaveBeenCalledWith(`/runs/${RUN.id}`);
  });

  it("says what to do next when there are no runs at all", async () => {
    stubFetch([{ path: "/runs", body: { items: [] } }]);
    renderWithSession(<RunsScreen />, { user: ADMIN });
    expect(await screen.findByText("No runs yet.")).toBeInTheDocument();
  });

  it("distinguishes an empty filter from an empty system", async () => {
    stubFetch([{ path: "/runs", body: { items: [] } }]);
    renderWithSession(<RunsScreen />, { user: ADMIN });
    await screen.findByText("No runs yet.");

    await userEvent.selectOptions(screen.getByLabelText("Filter by status"), "running");
    expect(await screen.findByText("No running runs.")).toBeInTheDocument();
  });

  it("surfaces a failure with the reference that traces it in the logs", async () => {
    stubFetch([
      {
        path: "/runs",
        status: 500,
        body: {
          error: {
            code: "internal.error",
            message: "The request failed unexpectedly.",
            details: {},
            request_id: "req_deadbeef",
          },
        },
      },
    ]);
    renderWithSession(<RunsScreen />, { user: ADMIN });

    expect(await screen.findByText("The request failed unexpectedly.")).toBeInTheDocument();
    expect(screen.getByText("req_deadbeef")).toBeInTheDocument();
  });
});
