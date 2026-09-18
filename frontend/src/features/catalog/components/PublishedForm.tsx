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
import type { PrimitiveType, PublicationField } from "@/lib/api";

export type Values = Record<string, unknown>;

/** What a control holds while it is being typed into. */
export type Draft = Record<string, string | boolean>;

const NUMERIC: PrimitiveType[] = ["integer", "number"];
const PATHLIKE: PrimitiveType[] = ["file", "directory"];
const STRUCTURED: PrimitiveType[] = ["object", "array"];

export function initialDraft(fields: PublicationField[]): Draft {
  const draft: Draft = {};
  for (const field of fields) {
    if (field.field_type === "boolean") {
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
 * Whether this field gets a file picker.
 *
 * A `directory` input never does: an upload is one file, and offering a
 * picker that cannot express what the field needs is the failure this
 * replaced.
 */
export function takesAnUpload(field: PublicationField): boolean {
  return field.field_type === "file" && sourcesOf(field).includes("upload");
}

function describe(field: PublicationField): string | undefined {
  if (field.help_text) return field.help_text;
  if (PATHLIKE.includes(field.field_type)) {
    const sources = sourcesOf(field);
    const where: string[] = [];
    // Said plainly, and only `url` still has no control behind it: a picker
    // that cannot pick is worse than a sentence that explains.
    if (sources.includes("shared")) where.push("in shared storage");
    if (sources.includes("upload")) where.push("from this computer");
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
}: {
  fields: PublicationField[];
  draft: Draft;
  onChange: (key: string, value: string | boolean) => void;
  errorFor: (key: string) => string | undefined;
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
            <Field
              key={field.key}
              id={`field-${field.key}`}
              label={field.required ? `${field.label} (required)` : field.label}
              hint={describe(field)}
              error={errorFor(field.key)}
            >
              {(props) =>
                takesAnUpload(field) ? (
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
                    className="checkbox"
                    checked={draft[field.key] === true}
                    onChange={(event) => onChange(field.key, event.target.checked)}
                  />
                ) : STRUCTURED.includes(field.field_type) ? (
                  <textarea
                    {...props}
                    className="editor"
                    rows={5}
                    spellCheck={false}
                    value={String(draft[field.key] ?? "")}
                    onChange={(event) => onChange(field.key, event.target.value)}
                  />
                ) : (
                  <input
                    {...props}
                    type={NUMERIC.includes(field.field_type) ? "number" : "text"}
                    step={field.field_type === "integer" ? 1 : "any"}
                    spellCheck={false}
                    placeholder={field.placeholder ?? undefined}
                    value={String(draft[field.key] ?? "")}
                    onChange={(event) => onChange(field.key, event.target.value)}
                  />
                )
              }
            </Field>
          ))}
        </section>
      ))}
    </div>
  );
}
