import "@/test/next-navigation";

import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AdminScreen } from "@/features/admin/AdminScreen";
import { ADMIN, renderWithSession, stubFetch, type Route } from "@/test/render";

const OTHER = "00000000-0000-4000-8000-0000000000b9";

afterEach(() => vi.unstubAllGlobals());

function person(overrides: Record<string, unknown> = {}) {
  return {
    id: OTHER,
    email: "sam@example.org",
    display_name: "Sam",
    role: "researcher",
    is_active: true,
    must_change_password: false,
    last_login_at: "2026-09-18T09:00:00Z",
    created_at: "2026-09-01T09:00:00Z",
    ...overrides,
  };
}

const USERS = (items: unknown[]): Route => ({
  path: "/admin/users",
  body: { items, total: items.length },
});
const WORKERS = (items: unknown[] = []): Route => ({
  path: "/admin/workers",
  body: { items, total: items.length },
});
const AUDIT = (items: unknown[] = []): Route => ({
  path: "/admin/audit-events",
  body: { items, total: items.length },
});

function routes(...extra: Route[]): Route[] {
  // Order matters: the stub takes the first path that matches as a substring.
  return [...extra, WORKERS(), AUDIT(), USERS([person(), { ...person(), id: ADMIN.user_id }])];
}

describe("administering a deployment", () => {
  it("shows a one-time password once, and says it cannot be fetched again", async () => {
    stubFetch(
      routes({
        path: "/admin/users",
        method: "POST",
        status: 201,
        body: {
          user: person({ email: "new@example.org" }),
          one_time_password: "kQ2-generated",
        },
      }),
    );
    const user = userEvent.setup();
    renderWithSession(<AdminScreen />, { user: ADMIN });

    await user.click(await screen.findByRole("button", { name: "Add a person" }));
    await user.type(screen.getByLabelText("Email"), "new@example.org");
    await user.type(screen.getByLabelText("Name"), "A New Person");
    await user.click(screen.getByRole("button", { name: "Create" }));

    const shown = await screen.findByLabelText("One-time password");
    expect(shown).toHaveTextContent("kQ2-generated");
    expect(screen.getByText(/not stored anywhere it can be read again/)).toBeInTheDocument();
  });

  it("offers no control to change your own role or end your own access", async () => {
    // A deployment with no administrator has no way back in that does not
    // involve the database.
    stubFetch(routes());
    renderWithSession(<AdminScreen />, { user: ADMIN });

    const rows = await screen.findAllByRole("row");
    const mine = rows.find((row) => within(row).queryByText("you"));
    expect(mine).toBeDefined();
    expect(within(mine as HTMLElement).queryByRole("button")).toBeNull();
  });

  it("marks an account that has never signed in", async () => {
    stubFetch(routes(USERS([person({ must_change_password: true, last_login_at: null })])));
    renderWithSession(<AdminScreen />, { user: ADMIN });

    expect(await screen.findByText("has not signed in")).toBeInTheDocument();
    expect(screen.getByText("never")).toBeInTheDocument();
  });

  it("flags a worker that has stopped saying anything", async () => {
    stubFetch(
      routes(
        WORKERS([
          {
            id: "w-1",
            hostname: "vm-1",
            version: "0.1.0",
            status: "active",
            capacity: 4,
            started_at: "2026-09-18T09:00:00Z",
            last_heartbeat_at: "2026-09-18T09:00:00Z",
            heartbeat_age_seconds: 900,
            running_tasks: 2,
          },
        ]),
      ),
    );
    renderWithSession(<AdminScreen />, { user: ADMIN });

    const stale = await screen.findByText("900s ago");
    expect(stale).toHaveClass("badge--bad");
    expect(screen.getByText("2 of 4")).toBeInTheDocument();
  });

  it("says plainly when no worker has ever registered", async () => {
    stubFetch(routes());
    renderWithSession(<AdminScreen />, { user: ADMIN });

    expect(await screen.findByText("No worker has ever registered.")).toBeInTheDocument();
    expect(screen.getByText(/Nothing will be executed/)).toBeInTheDocument();
  });

  it("shows who changed what, with the detail that makes it answerable", async () => {
    stubFetch(
      routes(
        AUDIT([
          {
            id: "00000000-0000-4000-8000-0000000000c1",
            action: "user.role_changed",
            target_type: "user",
            target_id: OTHER,
            actor_id: ADMIN.user_id,
            actor_email: "admin@example.org",
            request_id: "req_abc",
            ip_address: "127.0.0.1",
            details: { was: "researcher", now: "admin" },
            created_at: "2026-09-19T09:00:00Z",
          },
        ]),
      ),
    );
    renderWithSession(<AdminScreen />, { user: ADMIN });

    expect(await screen.findByText("user.role_changed")).toBeInTheDocument();
    expect(screen.getByText("admin@example.org")).toBeInTheDocument();
    expect(screen.getByText("was: researcher · now: admin")).toBeInTheDocument();
  });
});
