import "@/test/next-navigation";

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EnvironmentsScreen } from "@/features/environments/EnvironmentsScreen";
import { ADMIN, renderWithSession, stubFetch, type Route } from "@/test/render";

const ENV_ID = "00000000-0000-4000-8000-0000000000e0";

afterEach(() => vi.unstubAllGlobals());

function environment(overrides: Record<string, unknown> = {}) {
  return {
    id: ENV_ID,
    name: "lab",
    description: null,
    status: "available",
    is_default: true,
    python_version: "3.12",
    current_generation_id: "00000000-0000-4000-8000-0000000000g1".replace("g", "a"),
    locked_reason: null,
    package_count: 2,
    editable: false,
    created_at: "2026-09-01T09:00:00Z",
    ...overrides,
  };
}

function detail(overrides: Record<string, unknown> = {}) {
  return {
    ...environment(),
    packages: [
      { name: "pandas", version: "2.2.1", editable_path: null },
      { name: "numpy", version: "1.26.4", editable_path: null },
    ],
    reproducible: true,
    reproducibility_note: null,
    ...overrides,
  };
}

const LIST = (items: unknown[]): Route => ({
  path: "/environments",
  body: { items, total: items.length },
});
const DETAIL = (body: unknown): Route => ({ path: `/environments/${ENV_ID}`, body });
const OPERATIONS = (items: unknown[] = []): Route => ({
  path: `/environments/${ENV_ID}/operations`,
  body: { items, total: items.length },
});
const CALLABLES: Route = {
  path: `/environments/${ENV_ID}/callables`,
  body: { module: null, modules: ["pandas", "numpy"], callables: [] },
};

// Order matters: the stub takes the first path that matches as a substring,
// so the sub-resources have to come before the detail route that is a prefix
// of them — an override goes between, not in front.
function routes(...extra: Route[]): Route[] {
  return [OPERATIONS(), CALLABLES, ...extra, DETAIL(detail()), LIST([environment()])];
}

describe("what a task can import", () => {
  it("lists what is installed", async () => {
    stubFetch(routes());
    renderWithSession(<EnvironmentsScreen />, { user: ADMIN });

    expect(await screen.findByText("pandas")).toBeInTheDocument();
    expect(screen.getByText("2.2.1")).toBeInTheDocument();
  });

  it("says an install does not disturb anything running", async () => {
    // The question an admin would otherwise have to ask somebody.
    stubFetch(routes());
    renderWithSession(<EnvironmentsScreen />, { user: ADMIN });

    expect(await screen.findByText(/keeps the generation it started with/)).toBeInTheDocument();
    expect(screen.getByText(/can take several minutes/)).toBeInTheDocument();
  });

  it("sends an install and waits for it", async () => {
    const { calls } = stubFetch(
      routes({
        path: `/environments/${ENV_ID}/packages`,
        method: "POST",
        body: {
          id: "op",
          operation: "install",
          specifier: "six",
          status: "succeeded",
          created_at: "2026-09-01T09:00:00Z",
        },
      }),
    );
    const user = userEvent.setup();
    renderWithSession(<EnvironmentsScreen />, { user: ADMIN });

    await user.type(await screen.findByLabelText("Install a package"), "six==1.16.0");
    await user.click(screen.getByRole("button", { name: "Install" }));

    await waitFor(() =>
      expect(
        calls.some((call) => call.url.includes("/packages") && call.init.method === "POST"),
      ).toBe(true),
    );
  });

  it("says when an editable install makes runs unreproducible", async () => {
    stubFetch(
      routes(
        DETAIL(
          detail({
            editable: true,
            reproducible: false,
            reproducibility_note:
              "Installed from a working tree: labUtils (/srv/labUtils). A run using this environment records what it used, but the source can change underneath it.",
            packages: [{ name: "labUtils", version: "0.4.0", editable_path: "/srv/labUtils" }],
          }),
        ),
      ),
    );
    renderWithSession(<EnvironmentsScreen />, { user: ADMIN });

    expect(await screen.findByRole("alert")).toHaveTextContent("working tree");
    expect(screen.getByText("from a working tree")).toBeInTheDocument();
  });

  it("offers to clear a lock a crashed build left behind", async () => {
    // Otherwise every later install is refused by something that is not
    // running.
    stubFetch(routes(DETAIL(detail({ locked_reason: "install pandas" }))));
    renderWithSession(<EnvironmentsScreen />, { user: ADMIN });

    expect(await screen.findByText("Busy: install pandas.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Clear the lock" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Install" })).not.toBeInTheDocument();
  });

  it("says plainly when there is no environment at all", async () => {
    stubFetch([LIST([])]);
    renderWithSession(<EnvironmentsScreen />, { user: ADMIN });

    expect(await screen.findByText("No environment yet.")).toBeInTheDocument();
    expect(screen.getByText(/the runner and the standard library/)).toBeInTheDocument();
  });
});
