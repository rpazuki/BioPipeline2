import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { PublicationLibraryScreen } from "./PublicationLibraryScreen";
import { ADMIN, renderWithSession, stubFetch } from "@/test/render";

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
  renderWithSession(<PublicationLibraryScreen />, { user: ADMIN });
  await screen.findByLabelText("Types and presets (YAML)");
  await userEvent.click(screen.getByText("Import existing types or named values"));
  fireEvent.change(screen.getByLabelText("Source to import (YAML or JSON)"), {
    target: { value: "N: {type: integer}" },
  });
  await userEvent.click(screen.getByRole("button", { name: "Preview merge into editor" }));
  expect(
    await screen.findByText("Import loaded into editor. Review, validate and save it."),
  ).toBeInTheDocument();
  expect(screen.getByLabelText("Types and presets (YAML)")).toHaveValue(merged);
  expect(screen.getByRole("button", { name: "Save library" })).toBeDisabled();
  expect(calls.some((call) => call.init.method === "PUT")).toBe(false);
});
