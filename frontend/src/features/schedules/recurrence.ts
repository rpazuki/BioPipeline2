/**
 * Composing a recurrence, and reading one back.
 *
 * ADR 0015 settled that RRULE is what the interface offers, which leaves two
 * jobs. Building one from a handful of choices, so nobody has to know that
 * `FREQ=WEEKLY;BYDAY=MO,TH;BYHOUR=2` is a thing — and turning one back into a
 * sentence, so a list of schedules can be read rather than decoded.
 *
 * **`describe` never guesses.** A rule it does not recognise is shown as
 * itself. Rendering "every day at 02:00" over something that in fact fires
 * hourly would be worse than showing the raw rule, because the person reading
 * it has no way to tell they are being misled.
 */

export type Cadence = "hourly" | "daily" | "weekly" | "monthly" | "custom";

export const WEEKDAYS = [
  { code: "MO", label: "Mon" },
  { code: "TU", label: "Tue" },
  { code: "WE", label: "Wed" },
  { code: "TH", label: "Thu" },
  { code: "FR", label: "Fri" },
  { code: "SA", label: "Sat" },
  { code: "SU", label: "Sun" },
] as const;

const WEEKDAY_NAMES: Record<string, string> = Object.fromEntries(
  WEEKDAYS.map(({ code, label }) => [code, label]),
);

export interface RecurrenceDraft {
  cadence: Cadence;
  /** Hours between windows, for `hourly`. */
  everyHours: number;
  /** "HH:MM" local to the schedule's own timezone. */
  time: string;
  weekdays: string[];
  monthDay: number;
  /** A rule typed by hand, for anything the choices above cannot say. */
  custom: string;
}

export const DEFAULT_DRAFT: RecurrenceDraft = {
  cadence: "daily",
  everyHours: 6,
  // Outside working hours by default: a schedule exists to have finished by
  // the time somebody looks.
  time: "02:00",
  weekdays: ["MO"],
  monthDay: 1,
  custom: "",
};

function hourAndMinute(time: string): { hour: number; minute: number } | null {
  const match = /^(\d{1,2}):(\d{2})$/.exec(time.trim());
  if (!match) return null;
  const hour = Number(match[1]);
  const minute = Number(match[2]);
  if (hour > 23 || minute > 59) return null;
  return { hour, minute };
}

export interface Composed {
  rrule: string | null;
  problem: string | null;
}

/** Turn the choices into a rule, or say what is wrong with them. */
export function compose(draft: RecurrenceDraft): Composed {
  if (draft.cadence === "custom") {
    const text = draft.custom.trim();
    if (!text) return { rrule: null, problem: "Write a recurrence rule, or pick a pattern." };
    if (!/FREQ=/i.test(text)) {
      return { rrule: null, problem: "A recurrence rule needs a FREQ, such as FREQ=DAILY." };
    }
    return { rrule: text, problem: null };
  }

  if (draft.cadence === "hourly") {
    if (!Number.isInteger(draft.everyHours) || draft.everyHours < 1 || draft.everyHours > 24) {
      return { rrule: null, problem: "Choose between 1 and 24 hours." };
    }
    return { rrule: `FREQ=HOURLY;INTERVAL=${draft.everyHours}`, problem: null };
  }

  const at = hourAndMinute(draft.time);
  if (!at) return { rrule: null, problem: "Give a time as HH:MM." };
  const clock = `BYHOUR=${at.hour};BYMINUTE=${at.minute};BYSECOND=0`;

  if (draft.cadence === "daily") return { rrule: `FREQ=DAILY;${clock}`, problem: null };

  if (draft.cadence === "weekly") {
    if (draft.weekdays.length === 0) {
      return { rrule: null, problem: "Pick at least one day." };
    }
    const days = WEEKDAYS.filter(({ code }) => draft.weekdays.includes(code)).map(
      ({ code }) => code,
    );
    return { rrule: `FREQ=WEEKLY;BYDAY=${days.join(",")};${clock}`, problem: null };
  }

  if (!Number.isInteger(draft.monthDay) || draft.monthDay < 1 || draft.monthDay > 31) {
    return { rrule: null, problem: "Choose a day of the month between 1 and 31." };
  }
  return { rrule: `FREQ=MONTHLY;BYMONTHDAY=${draft.monthDay};${clock}`, problem: null };
}

function parts(rule: string): Record<string, string> {
  // A stored rule carries its own DTSTART on a line of its own; the recurrence
  // is the RRULE line.
  const line =
    rule
      .split(/\r?\n/)
      .map((row) => row.trim())
      .find((row) => /FREQ=/i.test(row)) ?? "";
  const body = line.replace(/^RRULE:/i, "");
  const found: Record<string, string> = {};
  for (const pair of body.split(";")) {
    const [name, value] = pair.split("=");
    if (name && value) found[name.trim().toUpperCase()] = value.trim();
  }
  return found;
}

function clockOf(found: Record<string, string>): string | null {
  const hour = Number(found["BYHOUR"]);
  const minute = Number(found["BYMINUTE"] ?? "0");
  if (!Number.isInteger(hour) || hour < 0 || hour > 23) return null;
  if (!Number.isInteger(minute) || minute < 0 || minute > 59) return null;
  return `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
}

function ordinal(day: number): string {
  if (day % 100 >= 11 && day % 100 <= 13) return `${day}th`;
  return `${day}${["th", "st", "nd", "rd"][day % 10] ?? "th"}`;
}

/** A rule, an interval, or nothing, said in words a person can check. */
export function describe(
  rrule: string | null | undefined,
  intervalSeconds: number | null | undefined,
  timezone?: string | null,
): string {
  if (intervalSeconds) return `Every ${humanDuration(intervalSeconds)}`;
  if (!rrule) return "No recurrence";

  const found = parts(rrule);
  const every = Number(found["INTERVAL"] ?? "1");
  const zone = timezone && timezone !== "UTC" ? ` (${timezone})` : "";
  const sentence = (text: string) => `${text}${zone}`;

  switch ((found["FREQ"] ?? "").toUpperCase()) {
    case "HOURLY":
      if (found["BYHOUR"] || found["BYDAY"]) break;
      return every === 1 ? "Every hour" : `Every ${every} hours`;
    case "DAILY": {
      const clock = clockOf(found);
      if (!clock || found["BYDAY"] || found["BYMONTHDAY"]) break;
      return sentence(
        every === 1 ? `Every day at ${clock}` : `Every ${every} days at ${clock}`,
      );
    }
    case "WEEKLY": {
      const clock = clockOf(found);
      const days = (found["BYDAY"] ?? "").split(",").filter(Boolean);
      if (!clock || days.length === 0 || every !== 1) break;
      if (!days.every((day) => day in WEEKDAY_NAMES)) break;
      const named = days.map((day) => WEEKDAY_NAMES[day]).join(", ");
      return sentence(`Every ${named} at ${clock}`);
    }
    case "MONTHLY": {
      const clock = clockOf(found);
      const day = Number(found["BYMONTHDAY"]);
      if (!clock || !Number.isInteger(day) || day < 1 || day > 31 || every !== 1) break;
      return sentence(`The ${ordinal(day)} of every month at ${clock}`);
    }
  }

  // Unrecognised. Showing the rule itself is the honest answer: a sentence
  // that is almost right is one nobody can tell is wrong.
  return (
    rrule
      .split(/\r?\n/)
      .find((row) => /FREQ=/i.test(row))
      ?.replace(/^RRULE:/i, "") ?? rrule
  );
}

export function humanDuration(seconds: number): string {
  const units: [number, string][] = [
    [86_400, "day"],
    [3_600, "hour"],
    [60, "minute"],
  ];
  for (const [size, name] of units) {
    if (seconds % size === 0 && seconds >= size) {
      const count = seconds / size;
      return count === 1 ? name : `${count} ${name}s`;
    }
  }
  return `${seconds} seconds`;
}

/**
 * The zone the person is actually in.
 *
 * The right default for a schedule, because "02:00" means their 02:00. UTC
 * would be defensible and surprising.
 */
export function localZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

export function knownZones(): string[] {
  try {
    const supported = (
      Intl as unknown as { supportedValuesOf?: (key: string) => string[] }
    ).supportedValuesOf?.("timeZone");
    if (supported?.length) return supported;
  } catch {
    // Older engines: fall through to the one zone we can be sure of.
  }
  return [...new Set(["UTC", localZone()])];
}
