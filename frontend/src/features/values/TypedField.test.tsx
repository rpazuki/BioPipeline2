import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  PublishedForm,
  convert,
  initialDraft,
} from "@/features/catalog/components/PublishedForm";
import { renderWithSession, RESEARCHER, stubFetch, type Route } from "@/test/render";

afterEach(() => vi.unstubAllGlobals());

// The real type, from the deployment's own job definitions.
const RULE = {
  kind: "struct",
  key: "CustomReplicateRule",
  description: "Rule definition for custom replicate statistics aggregation.",
  fields: [
    {
      name: "direction",
      type: "enum",
      required: true,
      container: "single",
      options: [
        { label: "alphabetical", value: "alphabetical" },
        { label: "numerical", value: "numerical" },
      ],
    },
    { name: "pattern", type: "string", required: false, container: "single" },
    { name: "sample_size", type: "integer", required: true, container: "single" },
  ],
};

function field(overrides: Record<string, unknown> = {}) {
  return {
    key: "rules",
    label: "Replicate rule",
    field_type: "object",
    required: true,
    default_value: null,
    help_text: null,
    placeholder: null,
    ui_group: null,
    type_ref: "CustomReplicateRule",
    type_schema: RULE,
    saveable: true,
    source_policy: {},
    ...overrides,
  };
}

const NO_SAVED: Route = { path: "/saved-values", body: { items: [], total: 0 } };

function render(draft: Record<string, unknown>, onChange = vi.fn(), overrides = {}) {
  renderWithSession(
    <PublishedForm
      entry="od600"
      fields={[field(overrides)] as never}
      draft={draft}
      onChange={onChange}
      errorFor={() => undefined}
    />,
    { user: RESEARCHER },
  );
  return onChange;
}

describe("a field with a type", () => {
  it("asks for the type's fields one at a time, not as JSON", async () => {
    stubFetch([NO_SAVED]);
    render({ rules: {} });

    // What replaced a textarea and a hope: a select with the two real options.
    const direction = screen.getByLabelText("direction (required)");
    expect(within(direction as HTMLSelectElement).getAllByRole("option")).toHaveLength(3);
    expect(screen.getByLabelText("sample_size (required)")).toHaveAttribute("type", "number");
    expect(screen.getByLabelText("pattern")).toHaveAttribute("type", "text");
  });

  it("builds the object up field by field", async () => {
    stubFetch([NO_SAVED]);
    const onChange = render({ rules: { direction: "numerical" } });
    const user = userEvent.setup();

    // One keystroke: the draft is a prop here, so it does not accumulate
    // between them, and asserting on the last of three would be asserting on
    // the harness rather than the control.
    await user.type(screen.getByLabelText("sample_size (required)"), "7");

    // The existing key survives: a control that replaced the object each time
    // would lose whatever was filled in before it.
    expect(onChange).toHaveBeenLastCalledWith("rules", {
      direction: "numerical",
      sample_size: "7",
    });
  });

  it("sends the object as an object and lets the server coerce it", () => {
    // Not converted here: the server has to do it anyway, because a request
    // can arrive from anywhere, and two converters mean two answers.
    const fields = [field()] as never;
    const { values, problems } = convert(fields, {
      rules: { direction: "numerical", sample_size: "200" },
    });

    expect(values["rules"]).toEqual({ direction: "numerical", sample_size: "200" });
    expect(problems).toEqual({});
  });

  it("says a required typed field is empty rather than sending nothing", () => {
    const { problems } = convert([field()] as never, { rules: {} });
    expect(problems["rules"]).toContain("required");
  });

  it("starts empty rather than as a string", () => {
    expect(initialDraft([field()] as never)["rules"]).toEqual({});
  });
});

describe("saved values", () => {
  const SAVED = (items: unknown[]): Route => ({
    path: "/saved-values",
    body: { items, total: items.length },
  });

  it("offers what the researcher kept before", async () => {
    stubFetch([
      SAVED([
        {
          id: "00000000-0000-4000-8000-0000000000a1",
          type_key: "CustomReplicateRule",
          name: "Weekly plates",
          container: "single",
          value: { direction: "numerical", sample_size: 200 },
          type_schema: RULE,
          created_at: "2026-09-01T09:00:00Z",
          updated_at: "2026-09-01T09:00:00Z",
          usable: true,
          unusable_reason: null,
        },
      ]),
    ]);
    const onChange = render({ rules: {} });
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Weekly plates" }));

    expect(onChange).toHaveBeenCalledWith("rules", {
      direction: "numerical",
      sample_size: 200,
    });
  });

  it("shows one that no longer fits, disabled, with the reason", async () => {
    // Hiding it would leave the researcher wondering where their rule went.
    stubFetch([
      SAVED([
        {
          id: "00000000-0000-4000-8000-0000000000a2",
          type_key: "CustomReplicateRule",
          name: "Old rule",
          container: "single",
          value: { direction: "numerical" },
          type_schema: RULE,
          created_at: "2026-09-01T09:00:00Z",
          updated_at: "2026-09-01T09:00:00Z",
          usable: false,
          unusable_reason:
            "'Old rule' no longer fits this field: sample_size — This is required.",
        },
      ]),
    ]);
    render({ rules: {} });

    expect(await screen.findByRole("button", { name: "Old rule" })).toBeDisabled();
    expect(screen.getByText(/no longer fits this field/)).toBeInTheDocument();
  });

  it("keeps a filled-in value under a name", async () => {
    const { calls } = stubFetch([
      { path: "/saved-values", method: "POST", status: 201, body: { id: "x" } },
      NO_SAVED,
    ]);
    render({ rules: { direction: "numerical", sample_size: "200" } });
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Save this value" }));
    await user.type(screen.getByLabelText("Name for this value"), "Weekly plates");
    await user.click(screen.getByRole("button", { name: "Keep it" }));

    await waitFor(() =>
      expect(
        calls.some((call) => call.url.includes("entry=od600") && call.init.method === "POST"),
      ).toBe(true),
    );
  });

  it("is not offered on a field with no type", async () => {
    stubFetch([NO_SAVED]);
    render({ rules: "plain" }, vi.fn(), {
      type_schema: null,
      saveable: false,
      field_type: "string",
    });

    expect(screen.queryByRole("button", { name: "Save this value" })).not.toBeInTheDocument();
  });
});
