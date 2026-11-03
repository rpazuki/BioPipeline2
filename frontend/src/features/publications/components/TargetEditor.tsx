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
                <code>{'{"window": 5}'}</code>. Leave empty for no default. Uncheck the target
                to use its pipeline value.
              </p>
            </div>
          )}
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
                  onChange({ fieldType: event.target.value as PrimitiveType })
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
