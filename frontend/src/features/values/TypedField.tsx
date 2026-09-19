"use client";

/**
 * A control for a value that has a type.
 *
 * What replaced a JSON textarea. The real form asks for a
 * `CustomReplicateRule` — a direction chosen from two options, an optional
 * pattern, a sample size — and until now the only way to supply one was to
 * type the braces yourself and hope. The schema says exactly what the fields
 * are, so the form can ask for them one at a time.
 *
 * The schema is the one **frozen when the entry was published**, not whatever
 * the pipeline's definition says today. That is what makes an old entry keep
 * asking for what it asked for, and it is why this component takes a schema
 * rather than a type name.
 *
 * Values are held as they are typed and coerced by the server. The form does
 * not convert `"200"` to `200` itself: the server has to do it anyway — a
 * request can arrive from anywhere — and doing it twice means two places to
 * disagree about what a number is.
 */

import { Field } from "@/components/ui/Field";

export interface TypeSchema {
  kind?: string;
  key?: string;
  description?: string | null;
  default?: unknown;
  type?: string;
  options?: { label: string; value: unknown }[];
  fields?: TypeField[];
}

export interface TypeField {
  name: string;
  type: string;
  required?: boolean;
  default?: unknown;
  container?: string;
  description?: string | null;
  options?: { label: string; value: unknown }[];
  schema?: TypeSchema;
}

type Values = Record<string, unknown>;

const NUMERIC = ["integer", "number"];

function asText(value: unknown): string {
  if (value === null || value === undefined) return "";
  return typeof value === "string" ? value : JSON.stringify(value);
}

/** One field of a struct, rendered as whatever its type deserves. */
function Member({
  id,
  member,
  value,
  onChange,
  error,
}: {
  id: string;
  member: TypeField;
  value: unknown;
  onChange: (value: unknown) => void;
  error?: string | undefined;
}) {
  const label = member.required ? `${member.name} (required)` : member.name;

  // A list or a map of anything, and a nested struct, stay JSON for now: the
  // real definitions use neither, and a half-built repeater is worse than a
  // box that says what it wants.
  const structured = member.container !== "single" || Boolean(member.schema);

  return (
    <Field id={id} label={label} hint={member.description ?? undefined} error={error}>
      {(props) =>
        structured ? (
          <textarea
            {...props}
            className="editor"
            rows={3}
            spellCheck={false}
            value={asText(value)}
            onChange={(event) => onChange(event.target.value)}
          />
        ) : member.type === "enum" ? (
          <select {...props} value={asText(value)} onChange={(e) => onChange(e.target.value)}>
            {/* Blank first, so a required choice is a choice rather than
                whichever option happened to be listed first. */}
            <option value="">—</option>
            {(member.options ?? []).map((option) => (
              <option key={String(option.value)} value={String(option.value)}>
                {option.label}
              </option>
            ))}
          </select>
        ) : member.type === "boolean" ? (
          <input
            {...props}
            type="checkbox"
            className="checkbox"
            checked={value === true || value === "true"}
            onChange={(event) => onChange(event.target.checked)}
          />
        ) : (
          <input
            {...props}
            type={NUMERIC.includes(member.type) ? "number" : "text"}
            step={member.type === "integer" ? 1 : "any"}
            spellCheck={false}
            value={asText(value)}
            onChange={(event) => onChange(event.target.value)}
          />
        )
      }
    </Field>
  );
}

export function TypedField({
  id,
  schema,
  value,
  onChange,
  problems,
}: {
  id: string;
  schema: TypeSchema;
  value: unknown;
  onChange: (value: unknown) => void;
  /** Server-side problems, keyed by the path the server reported. */
  problems?: Record<string, string>;
}) {
  // A scalar alias is a named string: one control, and the name is already on
  // the field's own label.
  if (schema.kind !== "struct") {
    return (
      <input
        id={id}
        type={NUMERIC.includes(schema.type ?? "") ? "number" : "text"}
        spellCheck={false}
        value={asText(value ?? schema.default)}
        onChange={(event) => onChange(event.target.value)}
      />
    );
  }

  const current = (value && typeof value === "object" ? value : {}) as Values;

  return (
    <fieldset className="typed" id={id}>
      {schema.description ? <p className="field__hint">{schema.description}</p> : null}
      {(schema.fields ?? []).map((member) => (
        <Member
          key={member.name}
          id={`${id}-${member.name}`}
          member={member}
          value={current[member.name] ?? member.default}
          error={problems?.[member.name]}
          onChange={(next) => onChange({ ...current, [member.name]: next })}
        />
      ))}
    </fieldset>
  );
}
