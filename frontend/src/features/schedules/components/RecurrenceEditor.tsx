"use client";

/**
 * Saying when, without anybody having to know what an RRULE is.
 *
 * Four patterns cover what schedules here are actually for, and a fifth lets
 * somebody write the rule by hand for the rest. Whatever is chosen, the
 * sentence underneath is rendered by reading the composed rule back — not by
 * echoing the choices — so it is a check on the rule rather than a restatement
 * of the form.
 */

import { Field } from "@/components/ui/Field";
import {
  compose,
  describe,
  knownZones,
  WEEKDAYS,
  type Cadence,
  type RecurrenceDraft,
} from "@/features/schedules/recurrence";
import type { DstPolicy } from "@/lib/api";

const CADENCES: { value: Cadence; label: string }[] = [
  { value: "hourly", label: "Every few hours" },
  { value: "daily", label: "Daily" },
  { value: "weekly", label: "Weekly" },
  { value: "monthly", label: "Monthly" },
  { value: "custom", label: "A rule I write" },
];

const DST: { value: DstPolicy; label: string }[] = [
  { value: "skip_nonexistent", label: "Skip that day" },
  { value: "shift_forward", label: "Run once the clocks have changed" },
  { value: "utc_only", label: "Keep the same instant, ignore local time" },
];

export function RecurrenceEditor({
  draft,
  onChange,
  timezone,
  onTimezone,
  dstPolicy,
  onDstPolicy,
}: {
  draft: RecurrenceDraft;
  onChange: (next: RecurrenceDraft) => void;
  timezone: string;
  onTimezone: (zone: string) => void;
  dstPolicy: DstPolicy;
  onDstPolicy: (policy: DstPolicy) => void;
}) {
  const composed = compose(draft);
  const set = (patch: Partial<RecurrenceDraft>) => onChange({ ...draft, ...patch });
  const usesLocalTime = draft.cadence !== "hourly";

  return (
    <div className="stack">
      <Field id="cadence" label="How often">
        {(props) => (
          <select
            {...props}
            value={draft.cadence}
            onChange={(event) => set({ cadence: event.target.value as Cadence })}
          >
            {CADENCES.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        )}
      </Field>

      {draft.cadence === "hourly" ? (
        <Field id="every-hours" label="Hours between runs">
          {(props) => (
            <input
              {...props}
              type="number"
              min={1}
              max={24}
              value={draft.everyHours}
              onChange={(event) => set({ everyHours: Number(event.target.value) })}
            />
          )}
        </Field>
      ) : null}

      {draft.cadence === "weekly" ? (
        <fieldset className="fieldset">
          <legend>Days</legend>
          <div className="button-row">
            {WEEKDAYS.map(({ code, label }) => {
              const on = draft.weekdays.includes(code);
              return (
                <button
                  key={code}
                  type="button"
                  className={on ? "button button--primary" : "button"}
                  aria-pressed={on}
                  onClick={() =>
                    set({
                      weekdays: on
                        ? draft.weekdays.filter((day) => day !== code)
                        : [...draft.weekdays, code],
                    })
                  }
                >
                  {label}
                </button>
              );
            })}
          </div>
        </fieldset>
      ) : null}

      {draft.cadence === "monthly" ? (
        <Field
          id="month-day"
          label="Day of the month"
          hint="A month without that day is skipped, not moved — the 31st runs seven times a year."
        >
          {(props) => (
            <input
              {...props}
              type="number"
              min={1}
              max={31}
              value={draft.monthDay}
              onChange={(event) => set({ monthDay: Number(event.target.value) })}
            />
          )}
        </Field>
      ) : null}

      {usesLocalTime && draft.cadence !== "custom" ? (
        <Field id="time" label="At">
          {(props) => (
            <input
              {...props}
              type="time"
              value={draft.time}
              onChange={(event) => set({ time: event.target.value })}
            />
          )}
        </Field>
      ) : null}

      {draft.cadence === "custom" ? (
        <Field
          id="custom-rule"
          label="Recurrence rule"
          hint="An iCalendar RRULE, such as FREQ=WEEKLY;BYDAY=MO,WE,FR;BYHOUR=6;BYMINUTE=0."
        >
          {(props) => (
            <input
              {...props}
              spellCheck={false}
              value={draft.custom}
              onChange={(event) => set({ custom: event.target.value })}
            />
          )}
        </Field>
      ) : null}

      <Field
        id="timezone"
        label="Timezone"
        hint="What the time above means. A schedule that must track working hours needs the lab's zone, not UTC."
      >
        {(props) => (
          <select
            {...props}
            value={timezone}
            onChange={(event) => onTimezone(event.target.value)}
          >
            {knownZones().map((zone) => (
              <option key={zone} value={zone}>
                {zone}
              </option>
            ))}
          </select>
        )}
      </Field>

      {/* Only worth asking about when there is a local time to be ambiguous. */}
      {usesLocalTime && timezone !== "UTC" ? (
        <Field
          id="dst-policy"
          label="When the clocks go forward and this time does not exist"
          hint="Once a year, in most zones, the hour this runs in is skipped."
        >
          {(props) => (
            <select
              {...props}
              value={dstPolicy}
              onChange={(event) => onDstPolicy(event.target.value as DstPolicy)}
            >
              {DST.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          )}
        </Field>
      ) : null}

      <p className={composed.problem ? "form__error" : "muted"} role="status">
        {composed.problem ?? describe(composed.rrule, null, timezone)}
      </p>
    </div>
  );
}
