import "@/test/next-navigation";

import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppShell } from "@/components/layout/AppShell";
import { ADMIN, RESEARCHER, renderWithSession, stubFetch } from "@/test/render";
import { router, setPathname } from "@/test/next-navigation";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  setPathname("/runs");
});

describe("navigation", () => {
  it("offers a researcher only what a researcher can use", () => {
    stubFetch([]);
    renderWithSession(<AppShell>content</AppShell>, { user: RESEARCHER });
    expect(screen.getByRole("link", { name: "Runs" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Pipelines" })).not.toBeInTheDocument();
  });

  it("offers an admin the authoring surface too", () => {
    stubFetch([]);
    renderWithSession(<AppShell>content</AppShell>, { user: ADMIN });
    expect(screen.getByRole("link", { name: "Pipelines" })).toBeInTheDocument();
  });

  it("marks the current page for assistive technology, not just visually", () => {
    stubFetch([]);
    setPathname("/runs/abc");
    renderWithSession(<AppShell>content</AppShell>, { user: ADMIN });
    expect(screen.getByRole("link", { name: "Runs" })).toHaveAttribute("aria-current", "page");
  });

  it("starts every page with a way past the navigation", () => {
    stubFetch([]);
    renderWithSession(<AppShell>content</AppShell>, { user: ADMIN });
    expect(screen.getByRole("link", { name: "Skip to content" })).toHaveAttribute(
      "href",
      "#main",
    );
  });
});

describe("an admin page opened by a researcher", () => {
  it("says so rather than rendering a screen of failed requests", () => {
    // Not a security control — the backend refuses these requests whatever
    // this renders. It is here so nobody walks into a wall of 403s.
    stubFetch([]);
    setPathname("/pipelines");
    renderWithSession(<AppShell>secret</AppShell>, { user: RESEARCHER });
    expect(screen.getByRole("alert")).toHaveTextContent("This page is for administrators.");
    expect(screen.queryByText("secret")).not.toBeInTheDocument();
  });
});

describe("an anonymous visitor", () => {
  it("is sent to the sign-in page", async () => {
    stubFetch([
      {
        path: "/auth/session",
        status: 401,
        body: { error: { code: "auth.required", message: "no", details: {} } },
      },
    ]);
    renderWithSession(<AppShell>content</AppShell>);
    await vi.waitFor(() => expect(router.replace).toHaveBeenCalledWith("/login"));
  });
});
