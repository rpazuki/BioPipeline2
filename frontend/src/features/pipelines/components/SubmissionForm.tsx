"use client";

/**
 * A submission form built from the revision's own compiled contract.
 *
 * What replaced a free-text JSON box. The box was not merely ugly: the person
 * filling it in had to already know the keys, which of them were required, and
 * whether each wanted a path or a value — none of which was written down
 * anywhere they could see. The compiler knows all three, and stores them with
 * the revision.
 *
 * What the contract does **not** carry is a scalar type for a `value` input.
 * A public input is one whose default is `$WILL_PROVIDE$`, so there is no
 * default to infer a type from, and the authoring format has no way to declare
 * one. Those render as text, and the value reaches the pipeline as a string.
 * See the note in the pipeline detail screen.
 */

import { Field } from "@/components/ui/Field";
import { UploadControl } from "@/features/uploads/UploadControl";
import type { CompiledInput, InputSourceMode } from "@/lib/api";

export type Values = Record<string, unknown>;

/** What a person is being asked for, in words rather than in schema terms. */
function describe(input: CompiledInput): string {
  const sources = input.sources ?? [];
  const where = sourcePhrase(sources);
  if (input.accept === "directory") return `A directory${where}.`;
  if (input.accept === "file") return `A file${where}.`;
  return "A value.";
}

function sourcePhrase(sources: InputSourceMode[]): string {
  const parts: string[] = [];
  // Said plainly, and only `url` still has no control behind it: a picker that
  // cannot pick is worse than a sentence that explains.
  if (sources.includes("shared")) parts.push("in shared storage");
  if (sources.includes("upload")) parts.push("from this computer");
  if (sources.includes("url")) parts.push("fetched from a URL (not supported yet)");
  return parts.length ? ` ${parts.join(", or ")}` : "";
}

/** A single file, and the pipeline says it may come from this machine. */
function takesAnUpload(input: CompiledInput): boolean {
  return input.accept === "file" && (input.sources ?? []).includes("upload");
}

function asText(value: unknown): string {
  if (value === undefined || value === null) return "";
  return typeof value === "string" ? value : JSON.stringify(value);
}

/** Which required inputs are still empty. */
export function missing(inputs: CompiledInput[], values: Values): string[] {
  return inputs
    .filter((input) => input.required)
    .filter((input) => {
      const value = values[input.key];
      return value === undefined || value === null || value === "";
    })
    .map((input) => input.key);
}

export function SubmissionForm({
  inputs,
  values,
  onChange,
  errorFor,
}: {
  inputs: CompiledInput[];
  values: Values;
  onChange: (key: string, value: unknown) => void;
  errorFor: (key: string) => string | undefined;
}) {
  if (inputs.length === 0) {
    return <p className="muted">This pipeline takes no submitted values. Run it as it is.</p>;
  }

  return (
    <div className="stack">
      {inputs.map((input) => {
        const structured = Boolean(input.type_ref);
        return (
          <Field
            key={input.key}
            id={`value-${input.key}`}
            label={input.required ? `${input.key} (required)` : input.key}
            hint={input.help ?? describeStructured(input, structured)}
            error={errorFor(input.key)}
          >
            {(props) =>
              takesAnUpload(input) ? (
                <UploadControl
                  id={props.id}
                  describedBy={props["aria-describedby"]}
                  value={asText(values[input.key])}
                  onChange={(next) => onChange(input.key, next)}
                  sources={input.sources ?? []}
                />
              ) : structured ? (
                <textarea
                  {...props}
                  className="editor"
                  rows={4}
                  spellCheck={false}
                  value={asText(values[input.key])}
                  onChange={(event) => onChange(input.key, event.target.value)}
                />
              ) : (
                <input
                  {...props}
                  type="text"
                  spellCheck={false}
                  value={asText(values[input.key])}
                  placeholder={input.accept === "value" ? "" : "/path/to/data"}
                  onChange={(event) => onChange(input.key, event.target.value)}
                />
              )
            }
          </Field>
        );
      })}
    </div>
  );
}

function describeStructured(input: CompiledInput, structured: boolean): string {
  if (!structured) return describe(input);
  return `${describe(input)} Typed as ${input.type_ref}; the type library is not served yet, so this is free text.`;
}
