import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { PublicationLibraryScreen } from "./PublicationLibraryScreen";
import { ADMIN, renderWithSession, stubFetch } from "@/test/render";

afterEach(() => vi.unstubAllGlobals());
const source = "definitions: {}\npresets: {}\n";
const library = { source_text: source, digest: "a".repeat(64), schemas: {}, presets: {} };

it("creates a type visually and preserves field metadata when switching to YAML", async () => {
  stubFetch([{ path: "/publication-library", body: library }]);
  renderWithSession(<PublicationLibraryScreen />, { user: ADMIN });
  await userEvent.click(await screen.findByRole("button", { name: "New type" }));
  fireEvent.change(screen.getByLabelText("Field label"), { target: { value: "Window size" } });
  await userEvent.selectOptions(screen.getByLabelText("Value type"), "integer");
  fireEvent.change(screen.getByLabelText("Help text"), {
    target: { value: "Number of consecutive items" },
  });
  await userEvent.click(screen.getByRole("button", { name: "YAML" }));
  const yaml = (screen.getByLabelText("Types and presets (YAML)") as HTMLTextAreaElement).value;
  expect(yaml).toContain("Window size");
  expect(yaml).toContain("type: integer");
  expect(yaml).toContain("Number of consecutive items");
  expect(screen.queryByText("Old project type library")).not.toBeInTheDocument();
});

it("validates on save and clears a previous validation report when source changes", async () => {
  const { calls } = stubFetch([
    { path: "/publication-library/validate", method: "POST", body: library },
    { path: "/publication-library", body: library },
    { path: "/publication-library", method: "PUT", body: library },
  ]);
  renderWithSession(<PublicationLibraryScreen />, { user: ADMIN });
  await userEvent.click(await screen.findByRole("button", { name: "YAML" }));
  await screen.findByLabelText("Types and presets (YAML)");
  const save = screen.getByRole("button", { name: "Save library" });
  expect(save).toBeEnabled();
  await userEvent.click(screen.getByRole("button", { name: "Validate" }));
  await waitFor(() => expect(save).toBeEnabled());
  await userEvent.click(save);
  expect(await screen.findByText("Publication library saved")).toBeInTheDocument();
  const sent = JSON.parse(String(calls.find((call) => call.init.method === "PUT")?.init.body));
  expect(sent).toEqual({ source_text: source, expected_digest: library.digest });
  await userEvent.type(screen.getByLabelText("Types and presets (YAML)"), " ");
  expect(save).toBeEnabled();
  expect(screen.queryByText("Library is valid")).not.toBeInTheDocument();
});

it("keeps unsaved text when another administrator has changed the library", async () => {
  stubFetch([
    { path: "/publication-library/validate", method: "POST", body: library },
    { path: "/publication-library", body: library },
    {
      path: "/publication-library",
      method: "PUT",
      status: 409,
      body: {
        error: { code: "conflict", message: "Library changed. Reload it.", details: {} },
      },
    },
  ]);
  renderWithSession(<PublicationLibraryScreen />, { user: ADMIN });
  await userEvent.click(await screen.findByRole("button", { name: "YAML" }));
  await screen.findByLabelText("Types and presets (YAML)");
  await userEvent.click(screen.getByRole("button", { name: "Validate" }));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Save library" })).toBeEnabled(),
  );
  await userEvent.click(screen.getByRole("button", { name: "Save library" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Library changed");
  expect(screen.getByLabelText("Types and presets (YAML)")).toHaveValue(source);
});
