/**
 * Compiler output, rendered.
 *
 * The compiler collects every problem rather than raising on the first, and
 * this shows every problem rather than the first — otherwise the author fixes
 * one error per round trip. Each carries its dotted location into the
 * document, which is the only thing that makes a message like "unresolvable
 * reference" actionable.
 */

import type { DiagnosticResponse } from "@/lib/api";

export function Diagnostics({ items }: { items: DiagnosticResponse[] }) {
  if (items.length === 0) return null;
  const errors = items.filter((item) => item.severity === "error");
  const warnings = items.filter((item) => item.severity === "warning");

  return (
    <div className="diagnostics" role="alert">
      <p className="diagnostics__summary">
        {errors.length > 0
          ? `${errors.length} error${errors.length === 1 ? "" : "s"}`
          : "Compiled"}
        {warnings.length > 0
          ? `, ${warnings.length} warning${warnings.length === 1 ? "" : "s"}`
          : ""}
      </p>
      <ul className="diagnostics__list">
        {[...errors, ...warnings].map((item, index) => (
          <li
            key={`${item.code}-${item.location}-${index}`}
            className={`diagnostic diagnostic--${item.severity}`}
          >
            <span className="diagnostic__code">{item.code}</span>
            {item.location ? <code className="diagnostic__where">{item.location}</code> : null}
            <span className="diagnostic__message">{item.message}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
