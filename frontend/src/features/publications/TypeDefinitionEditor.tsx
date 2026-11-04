"use client";

import { useState } from "react";
import { TypedField, type TypeSchema } from "@/features/values/TypedField";
import { mapping, previewSchema, type Mapping } from "./library-document";

const BUILTINS = ["string", "integer", "number", "boolean", "enum"];
const LABELS: Record<string, string> = {
  string: "Text",
  integer: "Integer",
  number: "Decimal",
  boolean: "Boolean",
  enum: "Choice",
};
export function TypeSelector({
  value,
  onChange,
  definitions = {},
  exclude,
}: {
  value: string;
  onChange: (value: string) => void;
  definitions?: Mapping;
  exclude?: string;
}) {
  return (
    <select className="form-select" value={value} onChange={(e) => onChange(e.target.value)}>
      {BUILTINS.map((type) => (
        <option key={type} value={type}>
          {LABELS[type]}
        </option>
      ))}
      {Object.keys(definitions)
        .filter((key) => key !== exclude)
        .map((key) => (
          <option key={key} value={key}>
            {String(mapping(definitions[key]).label || key)}
          </option>
        ))}
    </select>
  );
}

export function TypeDefinitionEditor({
  typeKey,
  definition,
  definitions,
  set,
  remove,
  move,
  rename,
}: {
  typeKey: string;
  definition: Mapping;
  definitions: Mapping;
  set: (path: string[], value: unknown) => void;
  remove: (path: string[]) => void;
  move: (key: string, offset: number) => void;
  rename: (key: string, name: string) => void;
}) {
  const [selected, select] = useState("");
  const fields = mapping(definition.fields);
  const keys = Object.keys(fields);
  const fieldKey = keys.includes(selected) ? selected : (keys[0] ?? "");
  const object = Object.hasOwn(definition, "fields");
  const node = object ? mapping(fields[fieldKey]) : definition;
  const path = object ? ["fields", fieldKey] : [];
  const update = (key: string, value: unknown) => set([...path, key], value);
  let schema: TypeSchema = { kind: "scalar", type: String(node.type || "string") };
  try {
    schema = definitions[String(node.type)]
      ? previewSchema(String(node.type), definitions)
      : {
          ...node,
          kind: "scalar",
          type: String(node.type || "string"),
          options: Array.isArray(node.options)
            ? node.options.map((o) =>
                typeof o === "object" && o && "value" in o
                  ? (o as { label: string; value: unknown })
                  : { label: String(o), value: o },
              )
            : [],
        };
    schema = {
      ...schema,
      container: String(node.container || "single"),
      has_default: false,
      default: undefined,
    };
  } catch {
    /* Invalid references are reported by the preview and server. */
  }
  let objectSchema: TypeSchema | undefined;
  try {
    objectSchema = previewSchema(typeKey, definitions);
  } catch {
    /* Invalid drafts remain editable. */
  }
  return (
    <div className="stack">
      <div className="form-grid">
        <label className="form-label">
          Display name
          <input
            className="form-control"
            value={String(definition.label || "")}
            onChange={(e) => set(["label"], e.target.value)}
          />
        </label>
        <label className="form-label">
          Definition kind
          <select
            className="form-select"
            value={object ? "object" : "simple"}
            onChange={(e) => {
              if (e.target.value === "object") {
                remove(["type"]);
                remove(["options"]);
                set(["fields"], { value: { type: "string", required: true, nullable: false } });
              } else {
                remove(["fields"]);
                set(["type"], "string");
              }
            }}
          >
            <option value="object">Object with fields</option>
            <option value="simple">Simple value</option>
          </select>
        </label>
      </div>
      <label className="form-label">
        Description
        <input
          className="form-control"
          value={String(definition.description || "")}
          onChange={(e) => set(["description"], e.target.value)}
        />
      </label>
      {object ? (
        <details>
          <summary>Object default and nullability</summary>
          <div className="stack stack--compact">
            <label className="form-check">
              <input
                type="checkbox"
                className="form-check-input"
                checked={definition.nullable === true}
                onChange={(e) => set(["nullable"], e.target.checked)}
              />
              Allow null for the whole object
            </label>
            <label className="form-check">
              <input
                type="checkbox"
                className="form-check-input"
                checked={Object.hasOwn(definition, "default")}
                onChange={(e) =>
                  e.target.checked ? set(["default"], {}) : remove(["default"])
                }
              />
              Supply an object default
            </label>
            {Object.hasOwn(definition, "default") && objectSchema ? (
              <TypedField
                id={`object-default-${typeKey}`}
                schema={{ ...objectSchema, default: undefined, has_default: false }}
                value={definition.default}
                onChange={(value) => set(["default"], value)}
              />
            ) : null}
          </div>
        </details>
      ) : null}
      <div className={object ? "type-designer" : "stack"}>
        {object ? (
          <aside className="type-designer__outline stack stack--compact">
            <h3>Fields</h3>
            {keys.map((key, index) => (
              <div key={key} className="type-designer__field">
                <button
                  type="button"
                  className={`btn ${key === fieldKey ? "btn-primary" : "btn-outline-secondary"}`}
                  onClick={(event) => {
                    if (event.currentTarget.closest("form")?.reportValidity() !== false)
                      select(key);
                  }}
                >
                  {String(mapping(fields[key]).label || key)}
                </button>
                <button
                  type="button"
                  className="btn btn-sm"
                  disabled={!index}
                  aria-label={`Move ${key} up`}
                  onClick={() => move(key, -1)}
                >
                  ↑
                </button>
                <button
                  type="button"
                  className="btn btn-sm"
                  disabled={index === keys.length - 1}
                  aria-label={`Move ${key} down`}
                  onClick={() => move(key, 1)}
                >
                  ↓
                </button>
              </div>
            ))}
            <button
              type="button"
              className="btn btn-outline-primary"
              onClick={() => {
                let key = `field_${keys.length + 1}`;
                while (Object.hasOwn(fields, key)) key += "_";
                set(["fields", key], { type: "string", required: false, nullable: false });
                select(key);
              }}
            >
              Add field
            </button>
          </aside>
        ) : null}
        {!object || fieldKey ? (
          <section className="stack type-designer__inspector">
            <div className="button-row">
              <h3>{object ? fieldKey : "Value definition"}</h3>
              {object ? (
                <button
                  type="button"
                  className="btn btn-sm btn-outline-danger"
                  disabled={keys.length === 1}
                  onClick={() => remove(["fields", fieldKey])}
                >
                  Remove field
                </button>
              ) : null}
            </div>
            {object ? (
              <label className="form-label">
                Field key
                <input
                  key={fieldKey}
                  className="form-control"
                  defaultValue={fieldKey}
                  onBlur={(e) => {
                    const key = e.target.value.trim();
                    if (key && key !== fieldKey && !Object.hasOwn(fields, key)) {
                      rename(fieldKey, key);
                      select(key);
                    } else e.target.value = fieldKey;
                  }}
                />
              </label>
            ) : null}
            <div className="form-grid">
              <label className="form-label">
                {object ? "Field label" : "Value label"}
                <input
                  className="form-control"
                  value={String(node.label || "")}
                  onChange={(e) => update("label", e.target.value)}
                />
              </label>
              <label className="form-label">
                Value type
                <TypeSelector
                  value={String(node.type || "string")}
                  definitions={object ? definitions : {}}
                  exclude={typeKey}
                  onChange={(type) => {
                    update("type", type);
                    if (type === "enum" && !node.options)
                      update("options", [{ label: "First choice", value: "first" }]);
                  }}
                />
              </label>
            </div>
            {object ? (
              <label className="form-label">
                Field shape
                <select
                  className="form-select"
                  value={String(node.container || "single")}
                  onChange={(e) => update("container", e.target.value)}
                >
                  <option value="single">Single</option>
                  <option value="list">List</option>
                  <option value="map">Named map</option>
                </select>
              </label>
            ) : null}
            <div className="button-row">
              {object ? (
                <label className="form-check">
                  <input
                    className="form-check-input"
                    type="checkbox"
                    checked={node.required === true}
                    onChange={(e) => update("required", e.target.checked)}
                  />
                  Required
                </label>
              ) : null}
              <label className="form-check">
                <input
                  type="checkbox"
                  className="form-check-input"
                  checked={node.nullable === true}
                  onChange={(e) => update("nullable", e.target.checked)}
                />
                Allow null
              </label>
              <label className="form-check">
                <input
                  type="checkbox"
                  className="form-check-input"
                  checked={Object.hasOwn(node, "default")}
                  onChange={(e) => {
                    if (e.target.checked)
                      update(
                        "default",
                        schema.kind === "struct" || schema.container === "map"
                          ? {}
                          : schema.container === "list"
                            ? []
                            : schema.type === "boolean"
                              ? false
                              : schema.type === "integer" || schema.type === "number"
                                ? 0
                                : "",
                      );
                    else remove([...path, "default"]);
                  }}
                />
                Supply a default
              </label>
            </div>
            {Object.hasOwn(node, "default") ? (
              <div className="stack stack--compact">
                <h4>Default value</h4>
                <TypedField
                  id={`default-${typeKey}-${fieldKey}`}
                  schema={schema}
                  value={node.default}
                  onChange={(value) => update("default", value)}
                />
              </div>
            ) : null}
            {node.type === "enum" ? (
              <>
                <label className="form-label">
                  Structured choice type
                  <select
                    className="form-select"
                    value={String(node.value_type || "")}
                    onChange={(e) =>
                      e.target.value
                        ? update("value_type", e.target.value)
                        : remove([...path, "value_type"])
                    }
                  >
                    <option value="">Primitive or custom YAML values</option>
                    {Object.keys(definitions)
                      .filter((key) => key !== typeKey)
                      .map((key) => (
                        <option key={key}>{key}</option>
                      ))}
                  </select>
                </label>
                <ChoiceEditor
                  definitions={definitions}
                  valueType={String(node.value_type || "")}
                  options={Array.isArray(node.options) ? node.options : []}
                  onChange={(options) => update("options", options)}
                />
              </>
            ) : null}
            {[
              ["help", "Help text"],
              ["example", "Example"],
              ["placeholder", "Placeholder"],
            ].map(([key, label]) => (
              <label className="form-label" key={key}>
                {label}
                <input
                  className="form-control"
                  value={String(node[key!] || "")}
                  onChange={(e) => update(key!, e.target.value)}
                />
              </label>
            ))}
            {node.type === "string" ? (
              <label className="form-label">
                Text presentation
                <select
                  className="form-select"
                  value={String(node.format || "plain")}
                  onChange={(e) => update("format", e.target.value)}
                >
                  <option value="plain">Single line</option>
                  <option value="text">Long text</option>
                  <option value="datetime">Date and time</option>
                </select>
              </label>
            ) : null}
          </section>
        ) : null}
      </div>
    </div>
  );
}

function ChoiceEditor({
  options,
  onChange,
  definitions,
  valueType,
}: {
  options: unknown[];
  onChange: (options: unknown[]) => void;
  definitions: Mapping;
  valueType: string;
}) {
  let optionSchema: TypeSchema | undefined;
  try {
    if (valueType) optionSchema = previewSchema(valueType, definitions);
  } catch {
    /* The main preview reports invalid references. */
  }
  const rows = options.map((option) =>
    option && typeof option === "object" && "value" in option
      ? (option as { label: string; value: unknown })
      : { label: String(option), value: option },
  );
  const update = (index: number, next: Partial<{ label: string; value: unknown }>) =>
    onChange(rows.map((row, i) => (i === index ? { ...row, ...next } : row)));
  return (
    <section className="stack stack--compact">
      <h4>Choices</h4>
      {rows.map((row, index) => (
        <div className="typed-collection__item stack stack--compact" key={index}>
          <label className="form-label">
            Choice label
            <input
              className="form-control"
              value={row.label}
              onChange={(e) => update(index, { label: e.target.value })}
            />
          </label>
          {optionSchema ? (
            <TypedField
              id={`option-${index}`}
              schema={optionSchema}
              value={row.value}
              onChange={(value) => update(index, { value })}
            />
          ) : (
            <>
              <label className="form-label">
                Returned value type
                <select
                  className="form-select"
                  value={typeof row.value === "object" ? "object" : typeof row.value}
                  onChange={(e) =>
                    update(index, {
                      value:
                        e.target.value === "number"
                          ? 0
                          : e.target.value === "boolean"
                            ? false
                            : e.target.value === "object"
                              ? {}
                              : "",
                    })
                  }
                >
                  <option value="string">Text</option>
                  <option value="number">Number</option>
                  <option value="boolean">Boolean</option>
                  <option value="object">Structured value (YAML)</option>
                </select>
              </label>
              {typeof row.value === "object" ? (
                <ObjectChoice
                  key={index}
                  value={row.value}
                  onChange={(value) => update(index, { value })}
                />
              ) : typeof row.value === "number" ? (
                <NumericChoice
                  value={row.value}
                  onChange={(value) => update(index, { value })}
                />
              ) : (
                <TypedField
                  id={`option-${index}`}
                  schema={{
                    kind: "scalar",
                    type:
                      typeof row.value === "number"
                        ? "number"
                        : typeof row.value === "boolean"
                          ? "boolean"
                          : "string",
                  }}
                  value={row.value}
                  onChange={(value) =>
                    update(index, {
                      value,
                    })
                  }
                />
              )}
            </>
          )}
          <button
            type="button"
            className="btn btn-sm btn-outline-danger align-start"
            onClick={() => onChange(rows.filter((_, i) => i !== index))}
          >
            Remove choice
          </button>
        </div>
      ))}
      <button
        type="button"
        className="btn btn-outline-primary align-start"
        onClick={() => onChange([...rows, { label: "New choice", value: "new" }])}
      >
        Add choice
      </button>
    </section>
  );
}

import { parse, stringify } from "yaml";
function NumericChoice({
  value,
  onChange,
}: {
  value: number;
  onChange: (value: number) => void;
}) {
  const [text, setText] = useState(String(value));
  const [observed, setObserved] = useState(value);
  if (value !== observed) {
    setObserved(value);
    setText(String(value));
  }
  const invalid = text.trim() === "" || !Number.isFinite(Number(text));
  return (
    <label className="form-label">
      Returned numeric value
      <input
        type="number"
        className="form-control"
        step="any"
        value={text}
        ref={(node) =>
          node?.setCustomValidity(invalid ? "Enter a finite numeric choice value." : "")
        }
        onChange={(e) => {
          setText(e.target.value);
          const value = Number(e.target.value);
          if (e.target.value.trim() && Number.isFinite(value)) {
            setObserved(value);
            onChange(value);
          }
        }}
      />
    </label>
  );
}
function ObjectChoice({
  value,
  onChange,
}: {
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const [text, setText] = useState(() => stringify(value));
  const [error, setError] = useState("");
  const [observed, setObserved] = useState(value);
  if (JSON.stringify(value) !== JSON.stringify(observed)) {
    setObserved(value);
    setText(stringify(value));
    setError("");
  }
  return (
    <label className="form-label">
      Returned value (YAML)
      <textarea
        className="form-control editor"
        rows={4}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          try {
            const parsed: unknown = parse(e.target.value, { uniqueKeys: true });
            setObserved(parsed);
            onChange(parsed);
            setError("");
          } catch (err) {
            setError(String(err));
          }
        }}
        ref={(node) => node?.setCustomValidity(error)}
      />
      {error ? (
        <span role="alert" className="field__error">
          {error}
        </span>
      ) : null}
    </label>
  );
}
