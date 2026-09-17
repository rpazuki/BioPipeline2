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
}: {
  target: BindableTarget;
  draft: FieldDraft;
  onChange: (next: Partial<FieldDraft>) => void;
  id: string;
}) {
  return (
    <li className={`target${draft.exposed ? " target--exposed" : ""}`}>
      <div className="target__head">
        <label className="target__toggle">
          <input
            type="checkbox"
            className="checkbox"
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
          <div className="field">
            <label className="field__label" htmlFor={`${id}-label`}>
              Label
            </label>
            <input
              id={`${id}-label`}
              type="text"
              value={draft.label}
              onChange={(event) => onChange({ label: event.target.value })}
            />
          </div>

          <div className="field">
            <label className="field__label" htmlFor={`${id}-help`}>
              Help text
            </label>
            <input
              id={`${id}-help`}
              type="text"
              placeholder="What a researcher needs to know to fill this in"
              value={draft.helpText}
              onChange={(event) => onChange({ helpText: event.target.value })}
            />
          </div>

          <div className="target__row">
            <div className="field">
              <label className="field__label" htmlFor={`${id}-type`}>
                Type
              </label>
              <select
                id={`${id}-type`}
                value={draft.fieldType}
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
              <label className="field__label" htmlFor={`${id}-group`}>
                Group
              </label>
              <input
                id={`${id}-group`}
                type="text"
                placeholder="Optional heading"
                value={draft.group}
                onChange={(event) => onChange({ group: event.target.value })}
              />
            </div>

            <div className="field">
              <label className="field__label" htmlFor={`${id}-required`}>
                Required
              </label>
              <input
                id={`${id}-required`}
                type="checkbox"
                className="checkbox"
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
