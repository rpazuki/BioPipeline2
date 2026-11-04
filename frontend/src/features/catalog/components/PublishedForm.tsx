"use client";

/**
 * The researcher's submission form, rendered from a publication's fields.
 *
 * Not a generic object editor: each field type gets the control that suits it,
 * because "how many points should the fit average over" deserves a number
 * input and not a JSON box. The labels, help text and grouping are the admin's
 * words — nothing here knows what a stage or a step is, and that is the point
 * of publishing.
 *
 * **Types are converted here, and this is the only place that can.** A form
 * control hands back a string; the pipeline wants an integer. The published
 * field type is the first point in the whole system that knows which — the
 * compiled IR does not carry a scalar type for a public input, and the
 * platform has no coercion step (see the gap recorded in
 * `migration/07-frontend-architecture.md`). So the conversion happens on the
 * way out, and a value that will not convert is reported against its own field
 * rather than sent and rejected.
 */

import { Field } from "@/components/ui/Field";
import { UploadControl } from "@/features/uploads/UploadControl";
import { DirectoryUploadControl } from "@/features/uploads/DirectoryUploadControl";
import { SavedValues } from "@/features/values/SavedValues";
import { TypedField, initialTypedValue, type TypeSchema } from "@/features/values/TypedField";
import type { PrimitiveType, PublicationField } from "@/lib/api";

export type Values = Record<string, unknown>;

/**
 * What a control holds while it is being typed into.
 *
 * `unknown`, not `string | boolean`, since a typed field holds the object a
 * researcher is building up — and the values inside it are still whatever the
 * controls handed back, because the server coerces them and doing it twice
 * means two places to disagree about what a number is.
 */
export type Draft = Record<string, unknown>;

const NUMERIC: PrimitiveType[] = ["integer", "number"];
const PATHLIKE: PrimitiveType[] = ["file", "directory"];
const STRUCTURED: PrimitiveType[] = ["object", "array"];

function schemaOf(field: PublicationField): TypeSchema | null {
  if (field.type_schema) return field.type_schema as TypeSchema;
  if (
    field.nullable !== null &&
    field.nullable !== undefined &&
    ["string", "integer", "number", "boolean"].includes(field.field_type)
  )
    return {
      kind: "scalar",
      type: field.field_type,
      nullable: field.nullable,
      placeholder: field.placeholder ?? undefined,
    };
  return null;
}

export function initialDraft(fields: PublicationField[]): Draft {
  const draft: Draft = {};
  for (const field of fields) {
    if (schemaOf(field)) {
      // An object under construction, not text: the control fills it in field
      // by field.
      const schema = schemaOf(field)!;
      draft[field.key] = field.has_default
        ? field.default_value
        : (field.default_value ?? initialTypedValue(schema));
    } else if (field.field_type === "boolean") {
      draft[field.key] = field.default_value === true;
    } else if (field.default_value !== null && field.default_value !== undefined) {
      draft[field.key] =
        typeof field.default_value === "string"
          ? field.default_value
          : JSON.stringify(field.default_value);
    } else {
      draft[field.key] = "";
    }
  }
  return draft;
}

export interface Converted {
  values: Values;
  problems: Record<string, string>;
}

/** Turn what was typed into what the API should receive. */
export function convert(fields: PublicationField[], draft: Draft): Converted {
  const values: Values = {};
  const problems: Record<string, string> = {};

  for (const field of fields) {
    const raw = draft[field.key];
    if (raw === null && field.nullable) {
      values[field.key] = null;
      continue;
    }

    if (schemaOf(field)) {
      // Sent as the object it is. The server validates it against the schema
      // frozen when this entry was published and reports per sub-field, which
      // is the only check that can be authoritative.
      const schema = schemaOf(field)!;
      const empty =
        raw === undefined ||
        raw === "" ||
        (schema.kind === "struct" &&
          (schema.fields ?? []).some(
            (member) =>
              member.required &&
              !(
                member.has_default ??
                (member.default !== undefined && member.default !== null)
              ),
          ) &&
          schema.container !== "list" &&
          schema.container !== "map" &&
          raw !== null &&
          typeof raw === "object" &&
          Object.keys(raw as object).length === 0);
      if (!empty || (raw === "" && schema.nullable !== undefined)) values[field.key] = raw;
      else if (field.required) problems[field.key] = `${field.label} is required.`;
      continue;
    }

    if (field.field_type === "boolean") {
      values[field.key] = raw === true;
      continue;
    }

    const text = typeof raw === "string" ? raw.trim() : "";
    if (text === "") {
      // Left blank: the server applies the field's default, or says it is
      // required. Sending "" would be a value, and a different one.
      if (field.required && field.default_value === null) {
        problems[field.key] = `${field.label} is required.`;
      }
      continue;
    }

    if (NUMERIC.includes(field.field_type)) {
      const parsed = Number(text);
      if (!Number.isFinite(parsed)) {
        problems[field.key] = "This must be a number.";
      } else if (field.field_type === "integer" && !Number.isInteger(parsed)) {
        problems[field.key] = "This must be a whole number.";
      } else {
        values[field.key] = parsed;
      }
      continue;
    }

    if (STRUCTURED.includes(field.field_type)) {
      try {
        values[field.key] = JSON.parse(text);
      } catch {
        problems[field.key] = "This is not valid JSON.";
      }
      continue;
    }

    values[field.key] = text;
  }

  return { values, problems };
}

export function sourcesOf(field: PublicationField): string[] {
  return (field.source_policy?.["sources"] as string[] | undefined) ?? [];
}

/**
 * Whether this field uses the single-file upload control.
 * Directory transfers use DirectoryUploadControl.
 */
export function takesAnUpload(field: PublicationField): boolean {
  return field.field_type === "file" && sourcesOf(field).includes("upload");
}

function describe(field: PublicationField): string | undefined {
  if (field.help_text) return field.help_text;
  if (field.type_schema) return undefined;
  if (PATHLIKE.includes(field.field_type)) {
    const sources = sourcesOf(field);
    const where: string[] = [];
    // Said plainly, and only `url` still has no control behind it: a picker
    // that cannot pick is worse than a sentence that explains.
    if (sources.includes("shared")) where.push("in shared storage");
    if (sources.includes("upload")) where.push("from this computer");
    if (sources.includes("folder")) where.push("uploaded as a folder");
    if (sources.includes("zip")) where.push("expanded from a ZIP archive");
    if (sources.includes("url")) where.push("fetched from a URL (not supported yet)");
    const noun = field.field_type === "directory" ? "directory" : "file";
    return where.length ? `A ${noun} ${where.join(", or ")}.` : `A ${noun}.`;
  }
  if (STRUCTURED.includes(field.field_type)) return "JSON.";
  return undefined;
}

export function PublishedForm({
  fields,
  draft,
  onChange,
  errorFor,
  entry,
  problems,
}: {
  fields: PublicationField[];
  draft: Draft;
  onChange: (key: string, value: unknown) => void;
  errorFor: (key: string) => string | undefined;
  /** The entry's slug, which saving a value needs to name its field. */
  entry?: string;
  problems?: Record<string, string>;
}) {
  if (fields.length === 0) {
    return <p className="muted">This entry takes no values. Start it as it is.</p>;
  }

  // Grouped as the admin grouped them; ungrouped fields keep their own order
  // rather than being swept into a bucket called "Other".
  const groups = new Map<string, PublicationField[]>();
  for (const field of fields) {
    const name = field.ui_group ?? "";
    groups.set(name, [...(groups.get(name) ?? []), field]);
  }

  return (
    <div className="stack">
      {[...groups.entries()].map(([group, members]) => (
        <section key={group || "ungrouped"} className="stack">
          {group ? <h3 className="form__group">{group}</h3> : null}
          {members.map((field) => (
            <div key={field.key} className="stack stack--compact">
              <Field
                key={field.key}
                id={`field-${field.key}`}
                label={field.required ? `${field.label} (required)` : field.label}
                hint={describe(field)}
                error={errorFor(field.key)}
              >
                {(props) =>
                  schemaOf(field) ? (
                    <>
                      <fieldset disabled={field.readonly}>
                        <TypedField
                          id={props.id}
                          schema={schemaOf(field)!}
                          value={draft[field.key]}
                          onChange={(next) => onChange(field.key, next)}
                          problems={problems}
                          path={field.key}
                          invalid={props["aria-invalid"]}
                          describedBy={props["aria-describedby"]}
                        />
                      </fieldset>
                      {entry && field.saveable && !field.readonly ? (
                        <SavedValues
                          entry={entry}
                          fieldKey={field.key}
                          value={draft[field.key]}
                          onUse={(next) => onChange(field.key, next)}
                        />
                      ) : null}
                    </>
                  ) : field.field_type === "directory" ? (
                    <DirectoryUploadControl
                      id={props.id}
                      invalid={props["aria-invalid"]}
                      describedBy={props["aria-describedby"]}
                      value={String(draft[field.key] ?? "")}
                      onChange={(next) => onChange(field.key, next)}
                      sources={sourcesOf(field).length ? sourcesOf(field) : ["shared"]}
                    />
                  ) : takesAnUpload(field) ? (
                    <UploadControl
                      id={props.id}
                      describedBy={props["aria-describedby"]}
                      value={String(draft[field.key] ?? "")}
                      onChange={(next) => onChange(field.key, next)}
                      sources={sourcesOf(field)}
                    />
                  ) : field.field_type === "boolean" ? (
                    <input
                      {...props}
                      type="checkbox"
                      className="checkbox form-check-input"
                      checked={draft[field.key] === true}
                      disabled={field.readonly}
                      onChange={(event) => onChange(field.key, event.target.checked)}
                    />
                  ) : STRUCTURED.includes(field.field_type) ? (
                    <textarea
                      {...props}
                      className="editor form-control"
                      rows={5}
                      disabled={field.readonly}
                      spellCheck={false}
                      value={String(draft[field.key] ?? "")}
                      onChange={(event) => onChange(field.key, event.target.value)}
                    />
                  ) : (
                    <input
                      className="form-control"
                      {...props}
                      type={NUMERIC.includes(field.field_type) ? "number" : "text"}
                      step={field.field_type === "integer" ? 1 : "any"}
                      spellCheck={false}
                      placeholder={field.placeholder ?? undefined}
                      disabled={field.readonly}
                      value={String(draft[field.key] ?? "")}
                      onChange={(event) => onChange(field.key, event.target.value)}
                    />
                  )
                }
              </Field>
              {entry && field.saveable && !schemaOf(field) && !field.readonly ? (
                <SavedValues
                  entry={entry}
                  fieldKey={field.key}
                  value={draft[field.key]}
                  onUse={(next) => onChange(field.key, next)}
                />
              ) : null}
            </div>
          ))}
        </section>
      ))}
    </div>
  );
}
