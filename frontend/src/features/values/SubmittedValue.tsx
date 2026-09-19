"use client";

/**
 * One submitted value, as something worth reading twice.
 *
 * A typed value is an object, and `JSON.stringify` turns it into a line of
 * braces. Both places this appears exist so somebody can *check* what was
 * submitted — the confirmation before a day of compute, and the record of
 * what a finished run was given — and a line of braces is not checkable.
 */

export function SubmittedValue({ value }: { value: unknown }) {
  if (value !== null && typeof value === "object" && !Array.isArray(value)) {
    return (
      <ul className="value-list">
        {Object.entries(value as Record<string, unknown>).map(([name, entry]) => (
          <li key={name}>
            <span className="muted">{name}</span> <code>{String(entry)}</code>
          </li>
        ))}
      </ul>
    );
  }
  return <code>{typeof value === "string" ? value : JSON.stringify(value)}</code>;
}
