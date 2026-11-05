"use client";

import { useId, useRef, useState } from "react";
import { Field } from "@/components/ui/Field";

export interface TypeSchema {
  kind?: string;
  key?: string;
  label?: string;
  description?: string | null;
  help?: string;
  example?: string;
  placeholder?: string;
  format?: string;
  default?: unknown;
  has_default?: boolean;
  nullable?: boolean;
  container?: string;
  type?: string;
  options?: { label: string; value: unknown }[];
  fields?: TypeField[];
}

export interface TypeField extends TypeSchema {
  name: string;
  type: string;
  required?: boolean;
  schema?: TypeSchema;
}

export function initialTypedValue(schema: TypeSchema): unknown {
  if (schema.has_default && schema.nullable && schema.default === null) return null;
  if (schema.container === "list" && !Array.isArray(schema.default)) return [];
  if (
    schema.container === "map" &&
    (!schema.default || typeof schema.default !== "object" || Array.isArray(schema.default))
  )
    return {};
  if (schema.has_default || (schema.default !== undefined && schema.default !== null))
    return structuredClone(schema.default);
  if (schema.container === "list") return [];
  if (schema.container === "map" || schema.kind === "struct") return {};
  return undefined;
}

export function memberSchema(member: TypeField): TypeSchema {
  return {
    ...(member.schema ?? { kind: "scalar", type: member.type, options: member.options }),
    ...Object.fromEntries(
      Object.entries(member).filter(([key]) =>
        [
          "label",
          "help",
          "example",
          "placeholder",
          "format",
          "nullable",
          "default",
          "has_default",
          "container",
        ].includes(key),
      ),
    ),
  };
}

type Props = {
  id: string;
  schema: TypeSchema;
  value: unknown;
  onChange: (value: unknown) => void;
  problems?: Record<string, string>;
  path?: string;
  formId?: string;
  invalid?: boolean;
  describedBy?: string;
};

/** Edit a complete typed value using recursive controls and stable collection rows. */
export function TypedField({
  id,
  schema,
  value,
  onChange,
  problems,
  path = "",
  formId,
  invalid,
  describedBy,
}: Props) {
  const current = value === undefined ? initialTypedValue(schema) : value;
  if (schema.nullable)
    return (
      <div className="stack stack--compact">
        <label className="form-check">
          <input
            form={formId}
            type="checkbox"
            className="form-check-input"
            checked={current === null}
            onChange={(e) =>
              onChange(
                e.target.checked
                  ? null
                  : (initialTypedValue({
                      ...schema,
                      default: undefined,
                      has_default: false,
                      nullable: false,
                    }) ??
                      (schema.type === "boolean"
                        ? false
                        : schema.type === "integer" || schema.type === "number"
                          ? 0
                          : schema.type === "enum"
                            ? schema.options?.[0]?.value
                            : "")),
              )
            }
          />
          <span className="form-check-label">Use null</span>
        </label>
        {current !== null ? (
          <TypedField
            {...{ id, value: current, onChange, problems, path, formId, invalid, describedBy }}
            schema={{ ...schema, nullable: false }}
          />
        ) : null}
      </div>
    );
  if (schema.container === "list" || schema.container === "map")
    return (
      <Collection
        {...{ id, schema, onChange, problems, path, formId, invalid, describedBy }}
        value={current}
      />
    );
  if (schema.kind === "struct") {
    const object =
      current && typeof current === "object" && !Array.isArray(current)
        ? (current as Record<string, unknown>)
        : {};
    const unknown = Object.keys(object).filter(
      (key) => !schema.fields?.some((member) => member.name === key),
    );
    return (
      <fieldset
        id={id}
        className="typed stack stack--compact"
        aria-invalid={invalid}
        aria-describedby={describedBy}
      >
        {schema.description ? <p className="field__hint">{schema.description}</p> : null}
        {current !== undefined &&
        current !== null &&
        (typeof current !== "object" || Array.isArray(current)) ? (
          <p role="alert" className="field__error">
            The stored value is not an object. Fill the fields to replace it.
          </p>
        ) : null}
        {(schema.fields ?? []).map((member) => {
          const fieldPath = path ? `${path}.${member.name}` : member.name;
          return (
            <Field
              key={member.name}
              id={`${id}-${member.name}`}
              label={`${member.label || member.name}${member.required ? " (required)" : ""}`}
              hint={member.help || member.description || undefined}
              error={problems?.[fieldPath]}
            >
              {(props) => (
                <TypedField
                  id={props.id}
                  schema={memberSchema(member)}
                  value={object[member.name]}
                  onChange={(next) => {
                    const updated = { ...object };
                    if (next === undefined) delete updated[member.name];
                    else updated[member.name] = next;
                    onChange(updated);
                  }}
                  problems={problems}
                  path={fieldPath}
                  formId={formId}
                  invalid={props["aria-invalid"]}
                  describedBy={props["aria-describedby"]}
                />
              )}
            </Field>
          );
        })}
        {unknown.length ? (
          <details open>
            <summary>Fields outside this type</summary>
            <p className="field__error">
              Review and remove these fields before saving against the selected type.
            </p>
            {unknown.map((key) => (
              <div className="typed-collection__item" key={key}>
                <strong>{key}</strong>
                <pre>{JSON.stringify(object[key], null, 2)}</pre>
                <button
                  type="button"
                  className="btn btn-sm btn-outline-danger"
                  onClick={() => {
                    const next = { ...object };
                    delete next[key];
                    onChange(next);
                  }}
                >
                  Remove extra field {key}
                </button>
              </div>
            ))}
          </details>
        ) : null}
      </fieldset>
    );
  }
  const text =
    current === undefined || current === null
      ? ""
      : typeof current === "string"
        ? current
        : JSON.stringify(current);
  if (schema.type === "enum")
    return (
      <select
        form={formId}
        id={id}
        aria-invalid={invalid}
        aria-describedby={describedBy}
        className="form-select"
        value={current === undefined ? "" : JSON.stringify(current)}
        onChange={(e) =>
          onChange(
            e.target.value === ""
              ? undefined
              : schema.options?.find(
                  (option) => JSON.stringify(option.value) === e.target.value,
                )?.value,
          )
        }
      >
        <option value="">Choose…</option>
        {(schema.options ?? []).map((option, index) => (
          <option key={index} value={JSON.stringify(option.value)}>
            {option.label}
          </option>
        ))}
      </select>
    );
  if (schema.type === "boolean")
    return (
      <select
        form={formId}
        id={id}
        aria-invalid={invalid}
        aria-describedby={describedBy}
        className="form-select"
        value={current === undefined ? "" : String(current)}
        onChange={(e) =>
          onChange(e.target.value === "" ? undefined : e.target.value === "true")
        }
      >
        <option value="">Choose…</option>
        <option value="true">Yes</option>
        <option value="false">No</option>
      </select>
    );
  const inputProps = {
    id,
    form: formId,
    "aria-invalid": invalid,
    "aria-describedby": describedBy,
    className: "form-control",
    value: text,
    placeholder: schema.placeholder || schema.example,
    onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
      onChange(e.target.value),
  };
  if (schema.format === "text") return <textarea {...inputProps} rows={4} />;
  return (
    <input
      {...inputProps}
      type={
        schema.format === "datetime"
          ? "datetime-local"
          : ["integer", "number"].includes(schema.type ?? "")
            ? "number"
            : "text"
      }
      step={schema.type === "integer" ? "1" : "any"}
    />
  );
}

interface Row {
  id: string;
  key: string;
  value: unknown;
}

function Collection({
  id,
  schema,
  value,
  onChange,
  problems,
  path = "",
  formId,
  invalid,
  describedBy,
}: Props) {
  const prefix = useId();
  const nextId = useRef(0);
  const map = schema.container === "map";
  const makeRows = (input: unknown): Row[] => {
    const entries = map
      ? Object.entries(input && typeof input === "object" && !Array.isArray(input) ? input : {})
      : (Array.isArray(input) ? input : []).map(
          (item, index) => [String(index), item] as [string, unknown],
        );
    return entries.map(([key, val], index) => ({
      id: `${prefix}-loaded-${index}`,
      key,
      value: val,
    }));
  };
  const [rows, setRows] = useState(() => makeRows(value));
  const [observed, setObserved] = useState(value);
  if (JSON.stringify(value) !== JSON.stringify(observed)) {
    setObserved(value);
    setRows(makeRows(value));
  }
  const element = { ...schema, container: "single", default: undefined, has_default: false };
  const duplicate = map && new Set(rows.map((row) => row.key)).size !== rows.length;
  const mismatched =
    value !== undefined &&
    value !== null &&
    (map ? typeof value !== "object" || Array.isArray(value) : !Array.isArray(value));
  function change(next: Row[]) {
    setRows(next);
    if (map && new Set(next.map((row) => row.key)).size !== next.length) return;
    const result = map
      ? Object.fromEntries(next.map((row) => [row.key, row.value]))
      : next.map((row) => row.value);
    setObserved(result);
    onChange(result);
  }
  return (
    <fieldset
      id={id}
      className="typed-collection stack stack--compact"
      aria-invalid={invalid}
      aria-describedby={describedBy}
    >
      {mismatched ? (
        <div role="alert" className="field__error">
          <p>
            The stored value is not {map ? "a named map" : "a list"}. Add entries to replace it.
          </p>
          <pre>{JSON.stringify(value, null, 2)}</pre>
        </div>
      ) : null}
      {duplicate ? (
        <p className="field__error" role="alert">
          Each map key must be unique. Resolve duplicate keys before saving.
        </p>
      ) : null}
      {rows.map((row, index) => (
        <section key={row.id} className="typed-collection__item stack stack--compact">
          <div className="button-row">
            {map ? (
              <label className="field__label form-label">
                Key
                <input
                  form={formId}
                  aria-label={`Key for entry ${index + 1}`}
                  className="form-control"
                  value={row.key}
                  ref={(input) => {
                    if (input)
                      input.setCustomValidity(duplicate ? "Each map key must be unique." : "");
                  }}
                  onChange={(e) =>
                    change(
                      rows.map((item) =>
                        item.id === row.id ? { ...item, key: e.target.value } : item,
                      ),
                    )
                  }
                />
              </label>
            ) : (
              <strong>Item {index + 1}</strong>
            )}
            {!map ? (
              <>
                <button
                  type="button"
                  className="btn btn-sm"
                  disabled={index === 0}
                  aria-label={`Move item ${index + 1} up`}
                  onClick={() => {
                    const next = [...rows];
                    [next[index - 1], next[index]] = [next[index]!, next[index - 1]!];
                    change(next);
                  }}
                >
                  ↑
                </button>
                <button
                  type="button"
                  className="btn btn-sm"
                  disabled={index === rows.length - 1}
                  aria-label={`Move item ${index + 1} down`}
                  onClick={() => {
                    const next = [...rows];
                    [next[index + 1], next[index]] = [next[index]!, next[index + 1]!];
                    change(next);
                  }}
                >
                  ↓
                </button>
              </>
            ) : null}
            <button
              type="button"
              className="btn btn-sm btn-outline-danger"
              onClick={() => change(rows.filter((item) => item.id !== row.id))}
            >
              Remove {map ? "entry" : "item"} {index + 1}
            </button>
          </div>
          <Field
            id={`${id}-${row.id}`}
            label={map ? `Value for ${row.key}` : `Value for item ${index + 1}`}
            error={problems?.[map ? `${path}.${row.key}` : `${path}[${index}]`]}
          >
            {(props) => (
              <TypedField
                id={`${id}-${row.id}`}
                schema={element}
                value={row.value}
                onChange={(next) =>
                  change(
                    rows.map((item) => (item.id === row.id ? { ...item, value: next } : item)),
                  )
                }
                problems={problems}
                path={map ? `${path}.${row.key}` : `${path}[${index}]`}
                formId={formId}
                invalid={props["aria-invalid"]}
                describedBy={props["aria-describedby"]}
              />
            )}
          </Field>
        </section>
      ))}
      <button
        type="button"
        className="btn btn-outline-primary align-start"
        onClick={() => {
          let key = `entry_${rows.length + 1}`;
          while (rows.some((row) => row.key === key)) key += "_";
          change([
            ...rows,
            {
              id: `${prefix}-added-${nextId.current++}`,
              key,
              value: initialTypedValue(element),
            },
          ]);
        }}
      >
        Add {map ? "named entry" : "item"}
      </button>
    </fieldset>
  );
}
