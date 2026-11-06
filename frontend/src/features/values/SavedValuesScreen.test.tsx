import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { ADMIN, RESEARCHER, renderWithSession, stubFetch } from "@/test/render";
import { SavedValuesScreen } from "./SavedValuesScreen";

afterEach(() => vi.unstubAllGlobals());
const schema = {
  kind: "struct",
  key: "Options",
  label: "Processing options",
  fields: [
    { name: "window", label: "Window", type: "integer", nullable: false, required: true },
  ],
};
const item = (id: string, name: string, window: number, is_default = false) => ({
  id,
  name,
  type_key: "Options",
  type_schema: schema,
  container: "single",
  value: { window },
  is_default,
  usable: true,
  created_at: "2026-11-04T10:00:00Z",
  updated_at: "2026-11-04T10:00:00Z",
});

it("keeps the initially selected case when a default update changes list order", async () => {
  const first = item("one", "Long", 21),
    second = item("two", "Short", 5);
  const body = { items: [first, second], total: 2 };
  stubFetch([
    { path: "/saved-values/contexts", body: [] },
    { path: "/saved-values/one", method: "PATCH", body: { ...first, is_default: true } },
    { path: "/saved-values", body },
  ]);
  renderWithSession(<SavedValuesScreen />, { user: RESEARCHER });
  await screen.findByRole("heading", { name: "Long" });
  body.items = [second, { ...first, is_default: true }];
  await userEvent.click(screen.getByRole("button", { name: "Set as my default" }));
  await screen.findByRole("button", { name: "Remove my default" });
  expect(screen.getByRole("button", { name: "Open saved value Long" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  expect(screen.getByLabelText("Window (required)")).toHaveValue(21);
  expect(screen.queryByRole("button", { name: "YAML value" })).not.toBeInTheDocument();
});

it("selects and edits named cases against their saved schema and sets a personal default", async () => {
  const first = item("one", "Short", 5, true),
    second = item("two", "Long", 21);
  const { calls } = stubFetch([
    { path: "/saved-values/contexts", body: [] },
    { path: "/saved-values/two", method: "PATCH", body: second },
    { path: "/saved-values", body: { items: [first, second], total: 2 } },
  ]);
  renderWithSession(<SavedValuesScreen />, { user: RESEARCHER });
  await userEvent.click(await screen.findByRole("button", { name: "Open saved value Long" }));
  expect(screen.getByLabelText("Window (required)")).toHaveValue(21);
  await userEvent.click(screen.getByRole("button", { name: "Set as my default" }));
  await waitFor(() => expect(calls.some((call) => call.init.method === "PATCH")).toBe(true));
  expect(
    JSON.parse(String(calls.find((call) => call.init.method === "PATCH")?.init.body)),
  ).toEqual({ is_default: true });
  await userEvent.clear(screen.getByLabelText("Name"));
  await userEvent.type(screen.getByLabelText("Name"), "Wide");
  await userEvent.click(screen.getByRole("button", { name: "Save value" }));
  await waitFor(() =>
    expect(calls.filter((call) => call.init.method === "PATCH")).toHaveLength(2),
  );
  expect(
    JSON.parse(String(calls.filter((call) => call.init.method === "PATCH")[1]?.init.body)),
  ).toEqual({ name: "Wide", value: { window: 21 }, replace_value: true });
});

it("lists every named value and opens another type directly from the list", async () => {
  const first = item("one", "Short", 5),
    second = item("two", "Long", 21);
  const third = {
    ...item("three", "Another configuration", 8),
    type_key: "OtherOptions",
    type_schema: { ...schema, key: "OtherOptions", label: "Other processing options" },
  };
  stubFetch([
    { path: "/saved-values/contexts", body: [] },
    { path: "/saved-values", body: { items: [first, second, third], total: 3 } },
  ]);
  renderWithSession(<SavedValuesScreen />, { user: RESEARCHER });
  expect(await screen.findByRole("button", { name: "Open saved value Short" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Open saved value Long" })).toBeVisible();
  const other = screen.getByRole("button", { name: "Open saved value Another configuration" });
  other.focus();
  await userEvent.keyboard("{Enter}");
  expect(screen.getByRole("heading", { name: "Another configuration" })).toBeInTheDocument();
  expect(screen.getByLabelText("Window (required)")).toHaveValue(8);
  expect(other).toHaveAttribute("aria-pressed", "true");
});

it("searches individual names and opens the matching value", async () => {
  stubFetch([
    { path: "/saved-values/contexts", body: [] },
    {
      path: "/saved-values",
      body: { items: [item("one", "Short", 5), item("two", "Long", 21)], total: 2 },
    },
  ]);
  renderWithSession(<SavedValuesScreen />, { user: RESEARCHER });
  await screen.findByRole("heading", { name: "Short" });
  await userEvent.type(screen.getByLabelText("Find saved values"), "LONG");
  expect(
    screen.queryByRole("button", { name: "Open saved value Short" }),
  ).not.toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Long" })).toBeInTheDocument();
  expect(screen.getByLabelText("Window (required)")).toHaveValue(21);
  await userEvent.click(screen.getByRole("button", { name: "Clear search" }));
  expect(screen.getByRole("button", { name: "Open saved value Short" })).toBeVisible();
  await userEvent.type(screen.getByLabelText("Find saved values"), "Processing options");
  expect(screen.getByRole("button", { name: "Open saved value Long" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Open saved value Short" })).toBeVisible();
});

it("shows a clear empty search state with a way back to the full list", async () => {
  stubFetch([
    { path: "/saved-values/contexts", body: [] },
    { path: "/saved-values", body: { items: [item("one", "Short", 5)], total: 1 } },
  ]);
  renderWithSession(<SavedValuesScreen />, { user: RESEARCHER });
  await screen.findByRole("heading", { name: "Short" });
  await userEvent.type(screen.getByLabelText("Find saved values"), "missing");
  expect(screen.getByText("No saved values match your search.")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Save value" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Clear search" }));
  expect(screen.getByRole("heading", { name: "Short" })).toBeInTheDocument();
});

it("opens another saved value after deleting the selected one", async () => {
  const first = item("one", "Short", 5),
    second = item("two", "Long", 21);
  const body = { items: [first, second], total: 2 };
  stubFetch([
    { path: "/saved-values/contexts", body: [] },
    { path: "/saved-values/one", method: "DELETE", status: 204 },
    { path: "/saved-values", body },
  ]);
  renderWithSession(<SavedValuesScreen />, { user: RESEARCHER });
  await userEvent.click(await screen.findByRole("button", { name: "Delete" }));
  body.items = [second];
  body.total = 1;
  await userEvent.click(screen.getByRole("button", { name: "Delete saved value" }));
  expect(await screen.findByRole("heading", { name: "Long" })).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Open saved value Short" }),
  ).not.toBeInTheDocument();
});

it.each([ADMIN, RESEARCHER])(
  "creates a private value through a published saveable field as $role",
  async (user) => {
    const created = item("new", "Example", 7);
    const { calls } = stubFetch([
      {
        path: "/saved-values/contexts",
        body: [
          {
            entry: "processing",
            field_key: "options",
            label: "Processing options",
            type_schema: schema,
          },
        ],
      },
      { path: "/saved-values", method: "POST", body: created },
      { path: "/saved-values", body: { items: [], total: 0 } },
    ]);
    renderWithSession(<SavedValuesScreen />, { user });
    await userEvent.click(screen.getByRole("button", { name: "New saved value" }));
    await userEvent.type(await screen.findByLabelText("Name"), "Example");
    expect(screen.queryByRole("button", { name: "YAML value" }) !== null).toBe(
      user.role === "admin",
    );
    await userEvent.type(screen.getByLabelText("Window (required)"), "7");
    await userEvent.click(screen.getByRole("button", { name: "Save personal value" }));
    await waitFor(() => expect(calls.some((call) => call.init.method === "POST")).toBe(true));
    const sent = calls.find((call) => call.init.method === "POST")!;
    expect(sent.url).toContain("entry=processing");
    expect(JSON.parse(String(sent.init.body))).toEqual({
      field_key: "options",
      name: "Example",
      value: { window: "7" },
    });
  },
);

it("keeps YAML editing available to administrators for existing personal values", async () => {
  stubFetch([
    { path: "/saved-values/contexts", body: [] },
    { path: "/saved-values", body: { items: [item("one", "Example", 7)], total: 1 } },
  ]);
  renderWithSession(<SavedValuesScreen />, { user: ADMIN });
  await userEvent.click(await screen.findByRole("button", { name: "YAML value" }));
  expect(screen.getByLabelText("Value (YAML)")).toHaveValue("window: 7\n");
});
