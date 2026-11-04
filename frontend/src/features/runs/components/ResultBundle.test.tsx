import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { ResultBundle } from "./ResultBundle";
import { renderWithSession, RESEARCHER, stubFetch } from "@/test/render";

afterEach(() => vi.unstubAllGlobals());
const job = {
  id: "job-id",
  run_id: "run-id",
  status: "pending",
  total_bytes: 10,
  completed_bytes: 0,
  artifact_id: null,
  message: null,
};

it("prepares a ZIP and offers a normal streaming download when ready", async () => {
  const { calls } = stubFetch([
    {
      path: "/runs/run-id/bundles/job-id",
      body: { ...job, status: "ready", artifact_id: "artifact-id", completed_bytes: 10 },
    },
    { path: "/runs/run-id/bundles", method: "POST", status: 201, body: job },
  ]);
  renderWithSession(<ResultBundle runId="run-id" live={false} />, { user: RESEARCHER });
  await userEvent.click(screen.getByRole("button", { name: "Prepare results ZIP" }));
  expect(await screen.findByRole("link", { name: "Download results ZIP" })).toHaveAttribute(
    "href",
    expect.stringContaining("/artifacts/artifact-id/download"),
  );
  expect(calls.filter((call) => call.init.method === "POST")).toHaveLength(1);
});

it("shows progress while the delivery service is preparing the archive", async () => {
  stubFetch([
    {
      path: "/runs/run-id/bundles/job-id",
      body: { ...job, status: "working", completed_bytes: 4 },
    },
    { path: "/runs/run-id/bundles", method: "POST", body: job },
  ]);
  renderWithSession(<ResultBundle runId="run-id" live={false} />, { user: RESEARCHER });
  await userEvent.click(screen.getByRole("button", { name: "Prepare results ZIP" }));
  await waitFor(() =>
    expect(
      screen.getByRole("progressbar", { name: "ZIP preparation progress" }),
    ).toHaveAttribute("value", "4"),
  );
  expect(screen.getByRole("button", { name: "Preparing ZIP…" })).toBeDisabled();
});

it("reports a failure and allows another preparation request", async () => {
  const { calls } = stubFetch([
    {
      path: "/runs/run-id/bundles/job-id",
      body: { ...job, status: "failed", message: "An output was removed." },
    },
    { path: "/runs/run-id/bundles", method: "POST", body: job },
  ]);
  renderWithSession(<ResultBundle runId="run-id" live={false} />, { user: RESEARCHER });
  await userEvent.click(screen.getByRole("button", { name: "Prepare results ZIP" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("An output was removed");
  await userEvent.click(screen.getByRole("button", { name: "Prepare results ZIP" }));
  await waitFor(() =>
    expect(calls.filter((call) => call.init.method === "POST")).toHaveLength(2),
  );
});
