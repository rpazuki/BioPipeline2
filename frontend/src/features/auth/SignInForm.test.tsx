import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SignInForm } from "@/features/auth/SignInForm";
import { ADMIN, renderWithSession, stubFetch } from "@/test/render";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("signing in", () => {
  it("sends the credentials and reports the session back", async () => {
    stubFetch([{ path: "/auth/login", method: "POST", body: ADMIN }]);
    const signedIn = vi.fn();
    renderWithSession(<SignInForm onSignedIn={signedIn} />, { user: null });

    await userEvent.type(screen.getByLabelText("Email"), "admin@example.org");
    await userEvent.type(screen.getByLabelText("Password"), "correct-horse-battery");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => expect(signedIn).toHaveBeenCalledWith(ADMIN));
  });

  it("puts a rejected password on the password field, not in a banner", async () => {
    // A message the user has to map back to a field themselves is a puzzle.
    stubFetch([
      {
        path: "/auth/login",
        method: "POST",
        status: 400,
        body: {
          error: {
            code: "request.invalid",
            message: "The request could not be understood.",
            details: { errors: [{ path: "password", message: "field required" }] },
          },
        },
      },
    ]);
    renderWithSession(<SignInForm />, { user: null });

    await userEvent.type(screen.getByLabelText("Email"), "admin@example.org");
    await userEvent.type(screen.getByLabelText("Password"), "x");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    const field = await screen.findByText("field required");
    const input = screen.getByLabelText("Password");
    expect(input).toHaveAttribute("aria-invalid", "true");
    // Associated, not merely adjacent: otherwise it does not exist to a
    // screen reader.
    expect(input.getAttribute("aria-describedby")).toContain(field.id);
  });

  it("shows a lockout message that names no field", async () => {
    stubFetch([
      {
        path: "/auth/login",
        method: "POST",
        status: 401,
        body: {
          error: {
            code: "auth.locked",
            message: "Too many failed attempts. Try again in 15 minutes.",
            details: {},
          },
        },
      },
    ]);
    renderWithSession(<SignInForm />, { user: null });

    await userEvent.type(screen.getByLabelText("Email"), "admin@example.org");
    await userEvent.type(screen.getByLabelText("Password"), "wrong");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Try again in 15 minutes.");
  });

  it("locks the email when re-authenticating, since we know who expired", async () => {
    stubFetch([]);
    renderWithSession(<SignInForm lockEmail="admin@example.org" submitLabel="Continue" />, {
      user: ADMIN,
    });
    expect(screen.getByLabelText("Email")).toHaveAttribute("readonly");
    expect(screen.getByRole("button", { name: "Continue" })).toBeInTheDocument();
  });
});
