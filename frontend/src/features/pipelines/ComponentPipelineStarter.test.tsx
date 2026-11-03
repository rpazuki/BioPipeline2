import "@/test/next-navigation";

import { screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import NewRevisionPage from "@/app/(app)/pipelines/new/page";
import { ADMIN, renderWithSession, stubFetch } from "@/test/render";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

it("starts a pipeline with the chosen component version and graph", async () => {
  stubFetch([]);
  const library = ".revisions/library/saved-version.yaml";
  const page = await NewRevisionPage({
    searchParams: Promise.resolve({ library, graph: "convert" }),
  });
  renderWithSession(page, { user: ADMIN });
  const source = screen.getByLabelText("Pipeline document") as HTMLTextAreaElement;
  expect(source.value).toContain(`library: "${library}"`);
  expect(source.value).toContain('graph: "convert"');
  expect(source.value).toContain("uses: selected_component");
  expect(screen.getByRole("button", { name: "Create revision" })).toBeDisabled();
});
