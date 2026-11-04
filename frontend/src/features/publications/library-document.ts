import { isMap, isScalar, parseDocument, type Document } from "yaml";
import type { TypeSchema, TypeField } from "@/features/values/TypedField";

export type Mapping = Record<string, unknown>;
export function mapping(value: unknown): Mapping {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Mapping) : {};
}

/** Parse source without discarding comments, mapping order, or unknown metadata. */
export function libraryDocument(source: string): Document {
  const document = parseDocument(source, { uniqueKeys: true });
  if (document.errors.length)
    throw new Error(document.errors.map((error) => error.message).join("\n"));
  if (!isMap(document.contents))
    throw new Error("The library needs definitions and presets mappings.");
  return document;
}

export function changeLibrary(
  source: string,
  path: string[],
  value: unknown,
  remove = false,
): string {
  const document = libraryDocument(source);
  if (remove) document.deleteIn(path);
  else document.setIn(path, value);
  return document.toString();
}

export function moveField(source: string, type: string, field: string, offset: number): string {
  const document = libraryDocument(source);
  const fields = document.getIn(["definitions", type, "fields"]);
  if (isMap(fields)) {
    const index = fields.items.findIndex((pair) => String(pair.key) === field);
    const target = index + offset;
    if (index >= 0 && target >= 0 && target < fields.items.length)
      [fields.items[index], fields.items[target]] = [
        fields.items[target]!,
        fields.items[index]!,
      ];
  }
  return document.toString();
}

export function renameLibraryKey(source: string, path: string[], name: string): string {
  const document = libraryDocument(source);
  const parent = document.getIn(path.slice(0, -1));
  if (!isMap(parent) || parent.has(name)) throw new Error("Use a unique key.");
  const pair = parent.items.find((item) => String(item.key) === path.at(-1));
  if (!pair) throw new Error("This entry is no longer in the draft.");
  if (isScalar(pair.key)) pair.key.value = name;
  else pair.key = document.createNode(name);
  return document.toString();
}

export function mergeLibrarySource(base: string, incoming: string): string {
  const document = libraryDocument(base),
    imported = libraryDocument(incoming);
  for (const section of ["definitions", "presets"]) {
    const entries = imported.get(section);
    if (isMap(entries))
      for (const pair of entries.items) {
        const key = String(pair.key);
        if (!document.hasIn([section, key])) document.setIn([section, key], pair.value);
      }
  }
  return document.toString();
}

/** Resolve a local draft for preview; the server independently validates saved source. */
export function previewSchema(
  key: string,
  definitions: Mapping,
  ancestors: string[] = [],
): TypeSchema {
  if (ancestors.includes(key) || ancestors.length > 8)
    throw new Error(`Type reference cycle at ${key}.`);
  const raw = mapping(definitions[key]);
  if (!Object.keys(raw).length) throw new Error(`Unknown type: ${key}.`);
  const base: TypeSchema = {
    ...raw,
    key,
    has_default: Object.hasOwn(raw, "default"),
  } as TypeSchema;
  if (raw.fields) {
    return {
      ...base,
      kind: "struct",
      fields: Object.entries(mapping(raw.fields)).map(([name, spec]) => {
        const field = mapping(spec);
        const type = String(field.type ?? "string");
        return {
          ...field,
          name,
          type,
          has_default: Object.hasOwn(field, "default"),
          options: options(field.options),
          ...(definitions[type]
            ? { schema: previewSchema(type, definitions, [...ancestors, key]) }
            : {}),
        } as TypeField;
      }),
    };
  }
  return { ...base, kind: "scalar", options: options(raw.options) };
}

function options(raw: unknown): TypeSchema["options"] {
  return Array.isArray(raw)
    ? raw.map((value) =>
        value && typeof value === "object" && "value" in value
          ? (value as { label: string; value: unknown })
          : { label: String(value), value },
      )
    : [];
}
