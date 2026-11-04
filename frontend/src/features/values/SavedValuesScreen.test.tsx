import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { RESEARCHER, renderWithSession, stubFetch } from "@/test/render";
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
  expect(screen.getByLabelText("Named saved value")).toHaveValue("one");
  expect(screen.getByLabelText("Window (required)")).toHaveValue(21);
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
  await userEvent.selectOptions(await screen.findByLabelText("Named saved value"), "two");
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

it("creates a private value only through a published saveable field", async () => {
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
  renderWithSession(<SavedValuesScreen />, { user: RESEARCHER });
  await userEvent.click(screen.getByRole("button", { name: "New saved value" }));
  await userEvent.type(await screen.findByLabelText("Name"), "Example");
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
});
