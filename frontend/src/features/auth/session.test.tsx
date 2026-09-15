import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ReauthDialog } from "@/features/auth/ReauthDialog";
import { useSession } from "@/features/auth/session";
import { ADMIN, renderWithSession, stubFetch } from "@/test/render";

afterEach(() => {
  vi.unstubAllGlobals();
});

/** A page with state a redirect would destroy. */
function WorkInProgress() {
  const { client } = useSession();
  return (
    <div>
      <ReauthDialog />
      <label htmlFor="notes">Notes</label>
      <textarea id="notes" defaultValue="" />
      <button type="button" onClick={() => void client.get("/runs").catch(() => {})}>
        Load runs
      </button>
    </div>
  );
}

describe("a session that expires while somebody is working", () => {
  it("asks them to sign in over the page instead of navigating away from it", async () => {
    stubFetch([
      {
        path: "/runs",
        status: 401,
        body: { error: { code: "auth.required", message: "Signed out.", details: {} } },
      },
    ]);
    renderWithSession(<WorkInProgress />, { user: ADMIN });

    const notes = screen.getByLabelText("Notes");
    await userEvent.type(notes, "half a submission form");

    await userEvent.click(screen.getByRole("button", { name: "Load runs" }));

    await screen.findByText("Your session has expired");
    // The point of the whole design: their work is still there.
    expect(screen.getByLabelText("Notes")).toHaveValue("half a submission form");
  });

  it("does not treat being signed out at all as an expiry", async () => {
    // The initial session probe 401s for every anonymous visitor. Showing them
    // a "your session expired" dialog on the login page would be nonsense.
    stubFetch([
      {
        path: "/auth/session",
        status: 401,
        body: { error: { code: "auth.required", message: "no session", details: {} } },
      },
    ]);
    renderWithSession(<ReauthDialog />);

    await waitFor(() =>
      expect(screen.queryByText("Your session has expired")).not.toBeInTheDocument(),
    );
  });
});
