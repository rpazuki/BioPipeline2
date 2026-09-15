/**
 * Putting the backend's field errors on the right inputs.
 *
 * The API reports validation problems as `details.errors[] = {path, message}`.
 * Rendering that list as a banner makes the user map each message back to a
 * field themselves, which for a thirty-field submission form is a puzzle. This
 * indexes them by path so a field can ask for its own.
 */

import { ApiError } from "@/lib/errors";

export interface FieldErrors {
  /** The message for one field path, if the failure named it. */
  for: (path: string) => string | undefined;
  /** Problems that named no field, or named one this form does not render. */
  unattached: string[];
  any: boolean;
}

export function fieldErrors(error: unknown, known: readonly string[] = []): FieldErrors {
  if (!(error instanceof ApiError)) {
    return { for: () => undefined, unattached: [], any: false };
  }

  const byPath = new Map<string, string>();
  const loose: string[] = [];

  for (const problem of error.fieldProblems()) {
    // "body.email" and "email" should both find the "email" field.
    const trimmed = problem.path.replace(/^body\./, "");
    const target = known.includes(trimmed)
      ? trimmed
      : known.find((candidate) => trimmed.endsWith(candidate));
    if (target && !byPath.has(target)) byPath.set(target, problem.message);
    else loose.push(problem.path ? `${problem.path}: ${problem.message}` : problem.message);
  }

  // A failure with no field detail is still the user's problem to see.
  if (byPath.size === 0 && loose.length === 0) loose.push(error.message);

  return {
    for: (path) => byPath.get(path),
    unattached: loose,
    any: byPath.size > 0 || loose.length > 0,
  };
}
