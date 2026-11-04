import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { LibraryTransferScreen } from "./LibraryTransferScreen";
import { ADMIN, renderWithSession, stubFetch } from "@/test/render";
import { parse } from "yaml";

afterEach(() => vi.unstubAllGlobals());

it("loads an import preview into the editor without saving it", async () => {
  const library = {
    source_text: "definitions: {}\npresets: {}\n",
    digest: "a".repeat(64),
    schemas: {},
    presets: {},
  };
  const merged = "definitions: {N: {type: integer}}\npresets: {}\n";
  const { calls } = stubFetch([
    {
      path: "/publication-library/import-preview",
      method: "POST",
      body: {
        source_text: merged,
        base_digest: library.digest,
        notes: ["No Python code was executed."],
      },
    },
    { path: "/publication-library", body: library },
  ]);
  renderWithSession(<LibraryTransferScreen />, { user: ADMIN });
  await screen.findByLabelText("Source to import (YAML or JSON)");
  fireEvent.change(screen.getByLabelText("Source to import (YAML or JSON)"), {
    target: { value: "N: {type: integer}" },
  });
  await userEvent.click(screen.getByRole("button", { name: "Preview conversion" }));
  expect(await screen.findByText("No Python code was executed.")).toBeInTheDocument();
  expect(
    parse((screen.getByLabelText("Merged library preview") as HTMLTextAreaElement).value),
  ).toEqual(parse(merged));
  expect(screen.getByRole("button", { name: "Save reviewed conversion" })).toBeEnabled();
  expect(calls.some((call) => call.init.method === "PUT")).toBe(false);
});
