import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { AuditScreen } from "./AuditScreen";
import { ADMIN, renderWithSession, stubFetch } from "@/test/render";

afterEach(() => vi.unstubAllGlobals());
const id = "00000000-0000-4000-8000-000000000001";
const event = {
  id,
  action: "run.submitted",
  target_type: "run",
  target_id: id,
  actor_email: "researcher@example.org",
  created_at: "2026-11-06T10:00:00Z",
  details: { status: "queued" },
};

it("shows run lifecycle audit history and searches by resource identifier", async () => {
  const { calls } = stubFetch([
    { path: "/admin/audit-events", body: { items: [event] } },
    { path: "/admin/deletions", body: { items: [] } },
  ]);
  renderWithSession(<AuditScreen />, { user: ADMIN });
  expect(await screen.findByText("run.submitted")).toBeInTheDocument();
  expect(await screen.findByText("researcher@example.org")).toBeInTheDocument();
  await userEvent.type(screen.getByLabelText("Run or resource identifier"), id);
  await userEvent.click(screen.getByRole("button", { name: "Search audit" }));
  await waitFor(() =>
    expect(calls.some((call) => call.url.includes(`target_id=${id}`))).toBe(true),
  );
});

it("shows failed cleanup and offers a retry without erasing its history", async () => {
  const { calls } = stubFetch([
    { path: "/admin/audit-events", body: { items: [] } },
    { path: `/admin/deletions/${id}/retry`, method: "POST", status: 202, body: {} },
    {
      path: "/admin/deletions",
      body: {
        items: [
          {
            id,
            target_type: "run",
            target_key: id,
            status: "failed",
            error: "Storage unavailable",
            created_at: "2026-11-06T10:00:00Z",
            completed_at: null,
          },
        ],
      },
    },
  ]);
  renderWithSession(<AuditScreen />, { user: ADMIN });
  expect(await screen.findByText("Storage unavailable")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Retry cleanup" }));
  await waitFor(() =>
    expect(
      calls.some((call) => call.init.method === "POST" && call.url.includes("/retry")),
    ).toBe(true),
  );
});
