"use client";

/**
 * One bindable target, and the field it becomes if exposed.
 *
 * The target's current value is shown whether or not it is exposed: an admin
 * deciding whether to let researchers change `moving_window_size` needs to
 * know it is 5 today, and where it lives.
 */

import type { BindableTarget, PrimitiveType } from "@/lib/api";
import type { FieldDraft } from "@/features/publications/model";
import type { PublicationLibrary } from "../usePublicationLibrary";
import { ValueEditor } from "@/features/values/ValueEditor";
import { initialTypedValue, type TypeSchema } from "@/features/values/TypedField";

const TYPES: PrimitiveType[] = [
  "string",
  "integer",
  "number",
  "boolean",
  "file",
  "directory",
  "url",
  "object",
  "array",
  "enum",
];

function where(target: BindableTarget): string {
  if (target.target === "default_value") return "asked for by the pipeline";
  if (target.target === "stage_input") return `input of stage ${target.stage}`;
  return `${target.stage} · ${target.step}`;
}

export function TargetEditor({
  target,
  draft,
  onChange,
  id,
  library,
}: {
  target: BindableTarget;
  draft: FieldDraft;
  onChange: (next: Partial<FieldDraft>) => void;
  id: string;
  library?: PublicationLibrary;
}) {
  const valueSchema: TypeSchema = {
    ...(library?.schemas[draft.typeRef] ?? { kind: "scalar", type: draft.fieldType }),
    container: draft.container ?? "single",
    nullable: draft.nullable,
  };
  let literal: unknown;
  try {
    literal = draft.valueText.trim() ? JSON.parse(draft.valueText) : undefined;
  } catch {
    literal = undefined;
  }
  const visualValue =
    !!draft.typeRef || ["string", "integer", "number", "boolean"].includes(draft.fieldType);
  return (
    <li className={`target${draft.exposed ? " target--exposed" : ""}`}>
      <div className="target__head">
        <label className="target__toggle">
          <input
            type="checkbox"
            className="checkbox form-check-input"
            checked={draft.exposed}
            onChange={(event) => onChange({ exposed: event.target.checked })}
          />
          <code>{target.key}</code>
        </label>
        <span className="muted">{where(target)}</span>
        {target.current_value !== null && target.current_value !== undefined ? (
          <span className="tag">now {JSON.stringify(target.current_value)}</span>
        ) : null}
      </div>

      {draft.exposed ? (
        <div className="target__body">
          {["file", "directory"].includes(draft.fieldType) ? (
            <fieldset className="field">
              <legend className="field__label form-label">Allowed input methods</legend>
              {(draft.fieldType === "file"
                ? ["upload", "shared"]
                : ["folder", "zip", "shared"]
              ).map((source) => (
                <label key={source} className="form-check">
                  <input
                    type="checkbox"
                    className="form-check-input"
                    checked={draft.sources.includes(source)}
                    onChange={(event) =>
                      onChange({
                        sources: event.target.checked
                          ? [...draft.sources, source]
                          : draft.sources.filter((item) => item !== source),
                      })
                    }
                  />
                  {
                    {
                      upload: "Upload a file",
                      folder: "Upload a folder",
                      zip: "Upload a ZIP archive",
                      shared: "Registered shared storage",
                    }[source]
                  }
                </label>
              ))}
            </fieldset>
          ) : null}
          <div className="target__row">
            <div className="field">
              <label className="field__label form-label" htmlFor={`${id}-mode`}>
                Value supplied by
              </label>
              <select
                className="form-select"
                id={`${id}-mode`}
                value={draft.valueMode}
                onChange={(event) =>
                  onChange({ valueMode: event.target.value as FieldDraft["valueMode"] })
                }
              >
                <option value="researcher">Ask the researcher</option>
                <option value="fixed">Fixed value (hidden from form)</option>
              </select>
            </div>
            <div className="field">
              <label className="field__label form-label" htmlFor={`${id}-preset`}>
                Library preset
              </label>
              <select
                className="form-select"
                id={`${id}-preset`}
                value={draft.presetRef}
                onChange={(event) => {
                  const preset = library?.presets[event.target.value];
                  const schema = preset ? library?.schemas[preset.type_ref] : undefined;
                  onChange({
                    presetRef: event.target.value,
                    ...(preset
                      ? {
                          typeRef: preset.type_ref,
                          container: (preset.container ?? "single") as FieldDraft["container"],
                          fieldType:
                            schema?.kind === "struct"
                              ? "object"
                              : (schema?.type as PrimitiveType),
                        }
                      : {}),
                  });
                }}
              >
                <option value="">Enter a value directly</option>
                {Object.keys(library?.presets ?? {}).map((key) => (
                  <option key={key}>{key}</option>
                ))}
              </select>
            </div>
            <div className="field">
              <label className="field__label form-label" htmlFor={`${id}-schema`}>
                Library type
              </label>
              <select
                className="form-select"
                id={`${id}-schema`}
                value={draft.typeRef}
                disabled={!!draft.presetRef}
                onChange={(event) => {
                  const schema = library?.schemas[event.target.value];
                  onChange({
                    typeRef: event.target.value,
                    ...(schema
                      ? {
                          fieldType:
                            schema.kind === "struct"
                              ? "object"
                              : (schema.type as PrimitiveType),
                        }
                      : {}),
                  });
                }}
              >
                <option value="">Use pipeline type</option>
                {Object.keys(library?.schemas ?? {}).map((key) => (
                  <option key={key}>{key}</option>
                ))}
              </select>
            </div>
          </div>
          {draft.presetRef ? (
            <p className="field__hint">
              Preset value:{" "}
              <code>{JSON.stringify(library?.presets[draft.presetRef]?.value)}</code>
            </p>
          ) : (
            <div className="field">
              {visualValue ? (
                <div className="stack stack--compact">
                  <label className="form-check">
                    <input
                      type="checkbox"
                      className="form-check-input"
                      checked={!!draft.valueText.trim()}
                      onChange={(e) =>
                        onChange({
                          valueText: e.target.checked
                            ? JSON.stringify(
                                initialTypedValue(valueSchema) ??
                                  (draft.fieldType === "boolean"
                                    ? false
                                    : draft.fieldType === "integer" ||
                                        draft.fieldType === "number"
                                      ? 0
                                      : ""),
                              )
                            : "",
                        })
                      }
                    />
                    {draft.valueMode === "fixed"
                      ? "Supply a fixed value"
                      : "Supply an editable default"}
                  </label>
                  {draft.valueText.trim() ? (
                    <ValueEditor
                      id={`${id}-literal`}
                      allowYaml
                      schema={valueSchema}
                      value={literal}
                      onChange={(value) =>
                        onChange({
                          valueText: value === undefined ? "" : JSON.stringify(value),
                        })
                      }
                    />
                  ) : null}
                </div>
              ) : (
                <>
                  <label className="field__label form-label" htmlFor={`${id}-value`}>
                    {draft.valueMode === "fixed" ? "Fixed value" : "Editable default"} (JSON)
                  </label>
                  <textarea
                    className="form-control"
                    id={`${id}-value`}
                    rows={2}
                    value={draft.valueText}
                    onChange={(event) => onChange({ valueText: event.target.value })}
                  />
                  <p className="field__hint">
                    Examples: <code>5</code>, <code>false</code>, <code>{'"text"'}</code>,{" "}
                    <code>{'{"window": 5}'}</code>. Leave empty for no default. Uncheck the
                    target to use its pipeline value.
                  </p>
                </>
              )}
            </div>
          )}
          {!["file", "directory"].includes(draft.fieldType) ? (
            <details className="stack">
              <summary>Value shape and personal saving</summary>
              <div className="stack stack--compact">
                <label className="form-label">
                  Value shape
                  <select
                    className="form-select"
                    value={draft.container ?? "single"}
                    disabled={!!draft.presetRef}
                    onChange={(e) =>
                      onChange({ container: e.target.value as FieldDraft["container"] })
                    }
                  >
                    <option value="single">Single</option>
                    <option value="list">List</option>
                    <option value="map">Named map</option>
                  </select>
                </label>
                <label className="form-label">
                  Personal saving
                  <select
                    className="form-select"
                    value={
                      draft.saveable === undefined ? "auto" : draft.saveable ? "yes" : "no"
                    }
                    onChange={(e) =>
                      onChange({
                        saveable:
                          e.target.value === "auto" ? undefined : e.target.value === "yes",
                      })
                    }
                  >
                    <option value="auto">Automatic for typed fields</option>
                    <option value="yes">Allow personal saved values</option>
                    <option value="no">Do not allow saving</option>
                  </select>
                </label>
                <label className="form-check">
                  <input
                    type="checkbox"
                    className="form-check-input"
                    checked={draft.allowPersonalDefault ?? false}
                    disabled={draft.saveable === false}
                    onChange={(e) => onChange({ allowPersonalDefault: e.target.checked })}
                  />
                  Allow a personal default
                </label>
                <label className="form-check">
                  <input
                    type="checkbox"
                    className="form-check-input"
                    checked={draft.nullable ?? false}
                    onChange={(e) => onChange({ nullable: e.target.checked })}
                  />
                  Allow null
                </label>
                {draft.valueMode === "researcher" ? (
                  <label className="form-check">
                    <input
                      type="checkbox"
                      className="form-check-input"
                      checked={draft.readonly ?? false}
                      onChange={(e) => onChange({ readonly: e.target.checked })}
                    />
                    Read-only visible value
                  </label>
                ) : null}
              </div>
            </details>
          ) : null}
          <details>
            <summary>Example and placeholder</summary>
            <div className="stack stack--compact">
              <label className="form-label">
                Example
                <input
                  className="form-control"
                  value={draft.example ?? ""}
                  onChange={(e) => onChange({ example: e.target.value })}
                />
              </label>
              <label className="form-label">
                Placeholder
                <input
                  className="form-control"
                  value={draft.placeholder ?? ""}
                  onChange={(e) => onChange({ placeholder: e.target.value })}
                />
              </label>
            </div>
          </details>
          <div className="field">
            <label className="field__label form-label" htmlFor={`${id}-label`}>
              Label
            </label>
            <input
              className="form-control"
              id={`${id}-label`}
              type="text"
              value={draft.label}
              onChange={(event) => onChange({ label: event.target.value })}
            />
          </div>

          <div className="field">
            <label className="field__label form-label" htmlFor={`${id}-help`}>
              Help text
            </label>
            <input
              className="form-control"
              id={`${id}-help`}
              type="text"
              placeholder="What a researcher needs to know to fill this in"
              value={draft.helpText}
              onChange={(event) => onChange({ helpText: event.target.value })}
            />
          </div>

          <div className="target__row">
            <div className="field">
              <label className="field__label form-label" htmlFor={`${id}-type`}>
                Type
              </label>
              <select
                className="form-select"
                id={`${id}-type`}
                value={draft.fieldType}
                disabled={!!draft.typeRef}
                onChange={(event) =>
                  onChange({
                    fieldType: event.target.value as PrimitiveType,
                    sources:
                      event.target.value === "file"
                        ? ["upload", "shared"]
                        : ["folder", "zip", "shared"],
                  })
                }
              >
                {TYPES.map((type) => (
                  <option key={type} value={type}>
                    {type}
                  </option>
                ))}
              </select>
            </div>

            <div className="field">
              <label className="field__label form-label" htmlFor={`${id}-group`}>
                Group
              </label>
              <input
                className="form-control"
                id={`${id}-group`}
                type="text"
                placeholder="Optional heading"
                value={draft.group}
                onChange={(event) => onChange({ group: event.target.value })}
              />
            </div>

            <div className="field">
              <label className="field__label form-label" htmlFor={`${id}-required`}>
                Required
              </label>
              <input
                id={`${id}-required`}
                type="checkbox"
                className="checkbox form-check-input"
                checked={draft.required}
                onChange={(event) => onChange({ required: event.target.checked })}
              />
            </div>
          </div>
        </div>
      ) : null}
    </li>
  );
}
