import { expect, it } from "vitest";
import {
  changeLibrary,
  libraryDocument,
  mergeLibrarySource,
  moveField,
  previewSchema,
  renameLibraryKey,
} from "./library-document";

const SOURCE = `# Shared library
definitions:
  Rule:
    label: Processing rule
    fields:
      # Window documentation
      window: {type: integer, required: true, nullable: false, custom_metadata: preserved}
      active: {type: boolean, default: false, nullable: false}
presets: {}
`;

it("patches one field without removing comments or unsupported metadata", () => {
  const source = changeLibrary(
    SOURCE,
    ["definitions", "Rule", "fields", "window", "help"],
    "Window size",
  );
  expect(source).toContain("# Shared library");
  expect(source).toContain("# Window documentation");
  expect(source).toContain("custom_metadata: preserved");
  const raw = libraryDocument(source).toJS();
  expect(raw.definitions.Rule.fields.active.default).toBe(false);
  expect(raw.definitions.Rule.fields.window.help).toBe("Window size");
});

it("moves complete field nodes with their comments", () => {
  const source = moveField(SOURCE, "Rule", "window", 1);
  expect(Object.keys(libraryDocument(source).toJS().definitions.Rule.fields)).toEqual([
    "active",
    "window",
  ]);
  expect(source).toContain("# Window documentation");
});

it("renames field keys in place without losing comments or changing order", () => {
  const source = renameLibraryKey(
    SOURCE,
    ["definitions", "Rule", "fields", "window"],
    "window_size",
  );
  expect(source).toContain("# Window documentation");
  expect(Object.keys(libraryDocument(source).toJS().definitions.Rule.fields)).toEqual([
    "window_size",
    "active",
  ]);
});

it("merges imports without reformatting existing type nodes", () => {
  const source = mergeLibrarySource(
    SOURCE,
    "definitions: {Count: {type: integer}}\npresets: {}\n",
  );
  expect(source).toContain("# Window documentation");
  expect(libraryDocument(source).toJS().definitions.Count.type).toBe("integer");
});

it("rejects duplicate YAML keys and recursive preview references", () => {
  expect(() => libraryDocument("definitions: {}\ndefinitions: {}\n")).toThrow();
  expect(() =>
    previewSchema("Loop", { Loop: { fields: { child: { type: "Loop" } } } }),
  ).toThrow(/cycle/);
});

it("resolves nested collection members and preserves explicit presence metadata", () => {
  const schema = previewSchema("Many", {
    Rule: { fields: { n: { type: "integer", nullable: false, required: true } } },
    Many: { fields: { rules: { type: "Rule", container: "list" } } },
  });
  expect(schema.fields?.[0]?.schema?.fields?.[0]?.nullable).toBe(false);
  expect(schema.fields?.[0]?.container).toBe("list");
});
