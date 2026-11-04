import { useState } from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { TypedField, type TypeSchema } from "./TypedField";
import { ValueEditor } from "./ValueEditor";

const schema: TypeSchema = {
  kind: "struct",
  fields: [
    { name: "window", label: "Window", type: "integer", nullable: false, required: true },
    { name: "enabled", type: "boolean", nullable: false },
  ],
};
function Harness({ shape = "single", initial = {} }: { shape?: string; initial?: unknown }) {
  const [value, setValue] = useState(initial);
  return (
    <>
      <TypedField
        id="value"
        schema={{ ...schema, container: shape }}
        value={value}
        onChange={(next) => setValue(JSON.parse(JSON.stringify(next)))}
      />
      <output data-testid="value">{JSON.stringify(value)}</output>
    </>
  );
}

it("edits nested objects in lists while keeping row focus after a source round trip", async () => {
  render(<Harness shape="list" initial={[]} />);
  await userEvent.click(screen.getByRole("button", { name: "Add item" }));
  const input = screen.getByLabelText("Window (required)");
  await userEvent.type(input, "123");
  expect(screen.getByLabelText("Window (required)")).toBe(input);
  expect(input).toHaveFocus();
  expect(screen.getByTestId("value")).toHaveTextContent('[{"window":"123"}]');
});

it("keeps duplicate map keys in the draft and blocks form validation without overwriting data", async () => {
  render(
    <form>
      <Harness shape="map" initial={{ first: { window: 1 }, second: { window: 2 } }} />
    </form>,
  );
  fireEvent.change(screen.getByLabelText("Key for entry 2"), { target: { value: "first" } });
  expect(screen.getByRole("alert")).toHaveTextContent("unique");
  expect(screen.getByLabelText("Key for entry 2")).toBeInvalid();
  expect(screen.getByTestId("value")).toHaveTextContent('"second":{"window":2}');
  fireEvent.change(screen.getByLabelText("Key for entry 2"), { target: { value: "third" } });
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.getByTestId("value")).toHaveTextContent('"third":{"window":2}');
});

it.each(["single", "list", "map"])(
  "retains an explicit null default for %s values",
  (container) => {
    render(
      <TypedField
        id="nullable"
        schema={{ ...schema, container, nullable: true, has_default: true, default: null }}
        value={undefined}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByRole("checkbox", { name: "Use null" })).toBeChecked();
    expect(screen.queryByLabelText("Window (required)")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add item" })).not.toBeInTheDocument();
  },
);

it("does not invent false for an unfilled Boolean", () => {
  const change = vi.fn();
  render(
    <TypedField
      id="flag"
      schema={{ kind: "scalar", type: "boolean" }}
      value={undefined}
      onChange={change}
    />,
  );
  expect(screen.getByRole("combobox")).toHaveValue("");
  expect(change).not.toHaveBeenCalled();
});

it("retains invalid YAML and prevents switching to a stale visual value", async () => {
  render(<ValueEditor id="source" schema={schema} value={{ window: 5 }} onChange={vi.fn()} />);
  await userEvent.click(screen.getByRole("button", { name: "YAML value" }));
  fireEvent.change(screen.getByLabelText("Value (YAML)"), { target: { value: "window: [" } });
  await userEvent.click(screen.getByRole("button", { name: "Visual value" }));
  expect(screen.getByLabelText("Value (YAML)")).toHaveValue("window: [");
  expect(screen.getByLabelText("Value (YAML)")).toBeInvalid();
});

it("preserves extra fields until a copied value is explicitly adapted", async () => {
  render(<Harness initial={{ window: 5, obsolete: "keep until reviewed" }} />);
  expect(screen.getByTestId("value")).toHaveTextContent("obsolete");
  await userEvent.click(screen.getByRole("button", { name: "Remove extra field obsolete" }));
  expect(screen.getByTestId("value")).toHaveTextContent('{"window":5}');
  expect(screen.queryByText("keep until reviewed")).not.toBeInTheDocument();
});
