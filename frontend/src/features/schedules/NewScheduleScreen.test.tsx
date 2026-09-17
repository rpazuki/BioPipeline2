import "@/test/next-navigation";

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { NewScheduleScreen } from "@/features/schedules/NewScheduleScreen";
import { ScheduleScreen } from "@/features/schedules/ScheduleScreen";
import { RESEARCHER, renderWithSession, stubFetch, type Route } from "@/test/render";

const SCHEDULE_ID = "00000000-0000-4000-8000-0000000000d1";

// Order matters: the stub takes the first path that matches as a substring,
// so the entry has to come before the list it is in.
const CATALOG: Route = {
  path: "/catalog",
  body: {
    items: [{ slug: "od600", title: "OD600 growth rates", description: null, version: 2 }],
  },
};

const ENTRY: Route = {
  path: "/catalog/od600",
  body: {
    slug: "od600",
    title: "OD600 growth rates",
    description: "Fit growth curves.",
    version: 2,
    publication_id: "00000000-0000-4000-8000-0000000000c1",
    revision_id: "00000000-0000-4000-8000-0000000000e1",
    fields: [
      {
        key: "experiment_folder",
        label: "Experiment folder",
        field_type: "directory",
        required: true,
        default_value: null,
        order_index: 0,
      },
      {
        key: "window",
        label: "Smoothing window",
        field_type: "integer",
        required: false,
        default_value: 5,
        order_index: 1,
      },
    ],
  },
};

const CREATED: Route = {
  path: "/schedules",
  method: "POST",
  status: 201,
  body: { id: SCHEDULE_ID },
};

afterEach(() => vi.unstubAllGlobals());

async function pickEntry(user: ReturnType<typeof userEvent.setup>) {
  await waitFor(() => expect(screen.getByLabelText("Catalog entry")).toBeInTheDocument());
  await user.selectOptions(screen.getByLabelText("Catalog entry"), "od600");
  await waitFor(() => expect(screen.getByLabelText(/Experiment folder/)).toBeInTheDocument());
}

describe("composing a schedule", () => {
  it("fills in the entry's own form, not a generic one", async () => {
    stubFetch([ENTRY, CATALOG]);
    const user = userEvent.setup();
    renderWithSession(<NewScheduleScreen />, { user: RESEARCHER });
    await pickEntry(user);

    // The admin's words and the admin's types, exactly as the catalog shows.
    expect(screen.getByLabelText(/Experiment folder/)).toHaveAttribute("type", "text");
    expect(screen.getByLabelText("Smoothing window")).toHaveAttribute("type", "number");
    // And its default, so a schedule left alone runs what the entry intends.
    expect(screen.getByLabelText("Smoothing window")).toHaveValue(5);
  });

  it("sends the values typed rather than as strings", async () => {
    const { calls } = stubFetch([ENTRY, CATALOG, CREATED]);
    const user = userEvent.setup();
    renderWithSession(<NewScheduleScreen />, { user: RESEARCHER });
    await pickEntry(user);

    await user.type(screen.getByLabelText("Name this schedule"), "Nightly");
    await user.type(screen.getByLabelText(/Experiment folder/), "/mnt/lab/run7");
    await user.clear(screen.getByLabelText("Smoothing window"));
    await user.type(screen.getByLabelText("Smoothing window"), "9");
    await user.click(screen.getByRole("button", { name: "Create schedule" }));

    await waitFor(() => {
      const post = calls.find((call) => (call.init.method ?? "GET") === "POST");
      expect(post).toBeDefined();
      const body = JSON.parse(String(post!.init.body));
      expect(body.values).toEqual({ experiment_folder: "/mnt/lab/run7", window: 9 });
      expect(body.slug).toBe("od600");
    });
  });

  it("composes a rule from the pattern chosen", async () => {
    const { calls } = stubFetch([ENTRY, CATALOG, CREATED]);
    const user = userEvent.setup();
    renderWithSession(<NewScheduleScreen />, { user: RESEARCHER });
    await pickEntry(user);

    await user.type(screen.getByLabelText("Name this schedule"), "Weekly");
    await user.type(screen.getByLabelText(/Experiment folder/), "/mnt/lab/run7");
    await user.selectOptions(screen.getByLabelText("How often"), "weekly");
    await user.click(screen.getByRole("button", { name: "Thu" }));
    await user.click(screen.getByRole("button", { name: "Create schedule" }));

    await waitFor(() => {
      const post = calls.find((call) => (call.init.method ?? "GET") === "POST");
      expect(post).toBeDefined();
      const body = JSON.parse(String(post!.init.body));
      expect(body.rrule).toBe("FREQ=WEEKLY;BYDAY=MO,TH;BYHOUR=2;BYMINUTE=0;BYSECOND=0");
    });
  });

  it("says what the rule means, read back from the rule itself", async () => {
    stubFetch([ENTRY, CATALOG]);
    const user = userEvent.setup();
    renderWithSession(<NewScheduleScreen />, { user: RESEARCHER });
    await waitFor(() => expect(screen.getByLabelText("How often")).toBeInTheDocument());
    await user.selectOptions(screen.getByLabelText("How often"), "hourly");
    expect(await screen.findByText("Every 6 hours")).toBeInTheDocument();
  });

  it("does not submit a schedule with nothing chosen", async () => {
    const { calls } = stubFetch([ENTRY, CATALOG, CREATED]);
    const user = userEvent.setup();
    renderWithSession(<NewScheduleScreen />, { user: RESEARCHER });
    await waitFor(() => expect(screen.getByLabelText("Catalog entry")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Create schedule" }));
    expect(calls.some((call) => (call.init.method ?? "GET") === "POST")).toBe(false);
  });

  it("drops the previous entry's values when the entry changes", async () => {
    // Two entries can both have a field called `window` and mean different
    // things by it; carrying a value across would be a silent wrong value.
    stubFetch([ENTRY, CATALOG]);
    const user = userEvent.setup();
    renderWithSession(<NewScheduleScreen />, { user: RESEARCHER });
    await pickEntry(user);
    await user.type(screen.getByLabelText(/Experiment folder/), "/mnt/lab/run7");
    await user.selectOptions(screen.getByLabelText("Catalog entry"), "");
    await user.selectOptions(screen.getByLabelText("Catalog entry"), "od600");
    await waitFor(() => expect(screen.getByLabelText(/Experiment folder/)).toHaveValue(""));
  });
});

describe("one schedule", () => {
  const detail = (overrides: Record<string, unknown> = {}) => ({
    path: `/schedules/${SCHEDULE_ID}`,
    body: {
      id: SCHEDULE_ID,
      title: "Nightly growth rates",
      status: "active",
      owner_id: RESEARCHER.user_id,
      slug: "od600",
      entry_title: "OD600 growth rates",
      version: 2,
      revision_is_current: true,
      rrule: "DTSTART:20260601T020000\nRRULE:FREQ=DAILY;BYHOUR=2;BYMINUTE=0",
      interval_seconds: null,
      timezone: "Europe/London",
      dst_policy: "skip_nonexistent",
      catchup_policy: "skip_missed",
      overlap_policy: "skip",
      max_concurrent_runs: 1,
      next_fire_at: "2026-06-02T01:00:00Z",
      last_fire_at: "2026-06-01T01:00:00Z",
      last_run_id: null,
      end_at: null,
      created_at: "2026-05-30T09:00:00Z",
      values: { experiment_folder: "/mnt/lab/run7" },
      fields: [
        {
          key: "experiment_folder",
          label: "Experiment folder",
          field_type: "directory",
          required: true,
          default_value: null,
          order_index: 0,
        },
      ],
      fires: [
        {
          fire_at: "2026-06-01T01:00:00Z",
          outcome: "created",
          run_id: "00000000-0000-4000-8000-0000000000f1",
          message: null,
        },
        {
          fire_at: "2026-05-31T01:00:00Z",
          outcome: "skipped_overlap",
          run_id: null,
          message: "1 run(s) from this schedule are still going.",
        },
      ],
      events: [{ event_type: "created", created_at: "2026-05-30T09:00:00Z", message: null }],
      ...overrides,
    },
  });

  it("says when it runs in words, not as a rule", async () => {
    stubFetch([detail()]);
    renderWithSession(<ScheduleScreen scheduleId={SCHEDULE_ID} />, { user: RESEARCHER });
    expect(
      await screen.findByText(/Every day at 02:00 \(Europe\/London\)/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/FREQ=/)).not.toBeInTheDocument();
  });

  it("shows the values with the admin's labels", async () => {
    stubFetch([detail()]);
    renderWithSession(<ScheduleScreen scheduleId={SCHEDULE_ID} />, { user: RESEARCHER });
    expect(await screen.findByText("Experiment folder")).toBeInTheDocument();
    expect(screen.getByText('"/mnt/lab/run7"')).toBeInTheDocument();
  });

  it("says why a window did not produce a run", async () => {
    // The question a schedule has to answer on sight.
    stubFetch([detail()]);
    renderWithSession(<ScheduleScreen scheduleId={SCHEDULE_ID} />, { user: RESEARCHER });
    expect(await screen.findByText("skipped, already running")).toBeInTheDocument();
    expect(
      screen.getByText("1 run(s) from this schedule are still going."),
    ).toBeInTheDocument();
  });

  it("says when its entry has been published again", async () => {
    stubFetch([detail({ revision_is_current: false })]);
    renderWithSession(<ScheduleScreen scheduleId={SCHEDULE_ID} />, { user: RESEARCHER });
    expect(
      await screen.findByText("This entry has been published again since."),
    ).toBeInTheDocument();
  });

  it("offers pause while it is active and resume while it is not", async () => {
    stubFetch([detail()]);
    renderWithSession(<ScheduleScreen scheduleId={SCHEDULE_ID} />, { user: RESEARCHER });
    expect(await screen.findByRole("button", { name: "Pause" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Resume" })).not.toBeInTheDocument();
  });

  it("warns that resuming drops the backlog", async () => {
    stubFetch([detail({ status: "paused", next_fire_at: null })]);
    renderWithSession(<ScheduleScreen scheduleId={SCHEDULE_ID} />, { user: RESEARCHER });
    expect(await screen.findByRole("button", { name: "Resume" })).toBeInTheDocument();
    expect(screen.getByText(/dropped/)).toBeInTheDocument();
  });

  it("asks before retiring one", async () => {
    stubFetch([detail()]);
    const user = userEvent.setup();
    renderWithSession(<ScheduleScreen scheduleId={SCHEDULE_ID} />, { user: RESEARCHER });
    await user.click(await screen.findByRole("button", { name: "Retire" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/history .* stay/)).toBeInTheDocument();
  });
});
