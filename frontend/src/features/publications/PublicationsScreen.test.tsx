import { screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { ADMIN, renderWithSession, stubFetch } from "@/test/render";
import { PublicationsScreen } from "./PublicationsScreen";

afterEach(() => vi.unstubAllGlobals());

it("opens publication views within Publications, including names used by other pages", async () => {
  stubFetch([
    {
      path: "/publications",
      body: {
        items: ["analysis", "library"].map((slug) => ({
          id: slug,
          slug,
          status: "published",
          created_at: "2026-11-06T10:00:00Z",
        })),
      },
    },
  ]);
  renderWithSession(<PublicationsScreen />, { user: ADMIN });
  const views = await screen.findAllByRole("link", { name: "View" });
  expect(views[0]).toHaveAttribute("href", "/publications/view/analysis");
  expect(views[1]).toHaveAttribute("href", "/publications/view/library");
});
