import "@/test/next-navigation";

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppShell } from "@/components/layout/AppShell";
import { ADMIN, renderWithSession, stubFetch, type Route } from "@/test/render";

afterEach(() => vi.unstubAllGlobals());

const CHANGED: Route = { path: "/auth/change-password", method: "POST", status: 204 };

describe("an account still on the password it was given", () => {
  it("is shown the change-password form instead of the application", async () => {
    // Every other request from this session is refused, so a page here would
    // be a page whose every button returns a 403.
    stubFetch([CHANGED]);
    renderWithSession(
      <AppShell>
        <p>the runs page</p>
      </AppShell>,
      { user: { ...ADMIN, must_change_password: true } },
    );

    expect(await screen.findByText("Choose your own password")).toBeInTheDocument();
    expect(screen.queryByText("the runs page")).not.toBeInTheDocument();
    expect(screen.getByText(/somebody else knows it/)).toBeInTheDocument();
  });

  it("says the change ends this session, because it does", async () => {
    const { calls } = stubFetch([CHANGED]);
    const user = userEvent.setup();
    renderWithSession(
      <AppShell>
        <p>the runs page</p>
      </AppShell>,
      { user: { ...ADMIN, must_change_password: true } },
    );

    await user.type(await screen.findByLabelText("The password you were given"), "given-one");
    await user.type(screen.getByLabelText("Your new password"), "one-they-chose-12");
    await user.click(screen.getByRole("button", { name: "Change it" }));

    expect(await screen.findByText("Password changed")).toBeInTheDocument();
    expect(screen.getByText(/including this one/)).toBeInTheDocument();
    expect(calls.some((call) => call.url.includes("/auth/change-password"))).toBe(true);
  });

  it("does not get in the way of an ordinary session", async () => {
    stubFetch([]);
    renderWithSession(
      <AppShell>
        <p>the runs page</p>
      </AppShell>,
      { user: ADMIN },
    );

    expect(await screen.findByText("the runs page")).toBeInTheDocument();
  });
});
