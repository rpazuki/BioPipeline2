import { describe as group, expect, it } from "vitest";

import {
  compose,
  DEFAULT_DRAFT,
  describe,
  humanDuration,
  type RecurrenceDraft,
} from "@/features/schedules/recurrence";

function draft(overrides: Partial<RecurrenceDraft> = {}): RecurrenceDraft {
  return { ...DEFAULT_DRAFT, ...overrides };
}

group("composing a rule", () => {
  it("builds a daily rule at a chosen time", () => {
    expect(compose(draft({ cadence: "daily", time: "02:30" })).rrule).toBe(
      "FREQ=DAILY;BYHOUR=2;BYMINUTE=30;BYSECOND=0",
    );
  });

  it("builds a weekly rule in calendar order, not click order", () => {
    const composed = compose(
      draft({ cadence: "weekly", weekdays: ["TH", "MO"], time: "07:00" }),
    );
    expect(composed.rrule).toBe("FREQ=WEEKLY;BYDAY=MO,TH;BYHOUR=7;BYMINUTE=0;BYSECOND=0");
  });

  it("builds an hourly rule", () => {
    expect(compose(draft({ cadence: "hourly", everyHours: 6 })).rrule).toBe(
      "FREQ=HOURLY;INTERVAL=6",
    );
  });

  it("builds a monthly rule", () => {
    expect(compose(draft({ cadence: "monthly", monthDay: 15, time: "23:05" })).rrule).toBe(
      "FREQ=MONTHLY;BYMONTHDAY=15;BYHOUR=23;BYMINUTE=5;BYSECOND=0",
    );
  });

  it("refuses a weekly rule with no days rather than composing a broken one", () => {
    const composed = compose(draft({ cadence: "weekly", weekdays: [] }));
    expect(composed.rrule).toBeNull();
    expect(composed.problem).toMatch(/at least one day/);
  });

  it("refuses a time it cannot read", () => {
    expect(compose(draft({ time: "half past two" })).problem).toMatch(/HH:MM/);
    expect(compose(draft({ time: "25:00" })).problem).toMatch(/HH:MM/);
  });

  it("passes a hand-written rule through", () => {
    expect(compose(draft({ cadence: "custom", custom: "FREQ=YEARLY;BYMONTH=3" })).rrule).toBe(
      "FREQ=YEARLY;BYMONTH=3",
    );
  });

  it("catches a hand-written rule that is not one", () => {
    expect(
      compose(draft({ cadence: "custom", custom: "every other tuesday" })).problem,
    ).toMatch(/FREQ/);
  });
});

group("reading a rule back", () => {
  it("reads the DTSTART the server adds", () => {
    expect(
      describe("DTSTART:20260601T020000\nRRULE:FREQ=DAILY;BYHOUR=2;BYMINUTE=0", null, "UTC"),
    ).toBe("Every day at 02:00");
  });

  it("names the zone when it is not UTC, because 02:00 means somebody's 02:00", () => {
    expect(describe("FREQ=DAILY;BYHOUR=2;BYMINUTE=0", null, "Europe/London")).toBe(
      "Every day at 02:00 (Europe/London)",
    );
  });

  it("names weekdays", () => {
    expect(describe("FREQ=WEEKLY;BYDAY=MO,TH;BYHOUR=7;BYMINUTE=0", null, "UTC")).toBe(
      "Every Mon, Thu at 07:00",
    );
  });

  it("reads a monthly rule with an ordinal that is not embarrassing", () => {
    expect(describe("FREQ=MONTHLY;BYMONTHDAY=1;BYHOUR=0;BYMINUTE=0", null, "UTC")).toBe(
      "The 1st of every month at 00:00",
    );
    expect(describe("FREQ=MONTHLY;BYMONTHDAY=11;BYHOUR=0;BYMINUTE=0", null, "UTC")).toBe(
      "The 11th of every month at 00:00",
    );
    expect(describe("FREQ=MONTHLY;BYMONTHDAY=22;BYHOUR=0;BYMINUTE=0", null, "UTC")).toBe(
      "The 22nd of every month at 00:00",
    );
  });

  it("reads an interval schedule, which has no rule at all", () => {
    expect(describe(null, 3600)).toBe("Every hour");
    expect(describe(null, 86_400)).toBe("Every day");
    expect(describe(null, 7_200)).toBe("Every 2 hours");
  });

  it("shows a rule it does not recognise as itself", () => {
    // The property that matters: a sentence that is almost right is one
    // nobody can tell is wrong.
    expect(describe("FREQ=YEARLY;BYMONTH=3;BYMONTHDAY=8", null, "UTC")).toBe(
      "FREQ=YEARLY;BYMONTH=3;BYMONTHDAY=8",
    );
    expect(
      describe("FREQ=WEEKLY;BYDAY=MO;INTERVAL=2;BYHOUR=2;BYMINUTE=0", null, "UTC"),
    ).toContain("INTERVAL=2");
  });

  it("does not claim a daily time for an hourly rule", () => {
    expect(describe("FREQ=HOURLY;INTERVAL=6", null, "UTC")).toBe("Every 6 hours");
  });

  it("says so when there is nothing", () => {
    expect(describe(null, null)).toBe("No recurrence");
  });

  it("round-trips everything it composes", () => {
    const cases: RecurrenceDraft[] = [
      draft({ cadence: "daily", time: "02:30" }),
      draft({ cadence: "weekly", weekdays: ["MO", "FR"], time: "09:15" }),
      draft({ cadence: "monthly", monthDay: 3, time: "00:00" }),
      draft({ cadence: "hourly", everyHours: 4 }),
    ];
    for (const one of cases) {
      const composed = compose(one);
      expect(composed.rrule).not.toBeNull();
      // Nothing composed here should ever fall through to the raw display.
      expect(describe(composed.rrule, null, "UTC")).not.toContain("FREQ=");
    }
  });
});

group("durations", () => {
  it("prefers the largest whole unit", () => {
    expect(humanDuration(60)).toBe("minute");
    expect(humanDuration(900)).toBe("15 minutes");
    expect(humanDuration(86_400)).toBe("day");
    expect(humanDuration(90)).toBe("90 seconds");
  });
});
