"use client";

/**
 * Composing a schedule: pick an entry, fill in its form, say when.
 *
 * The middle step renders the **same** `PublishedForm` the catalog does, not
 * an impression of it. A schedule is a submission somebody is not there to
 * make, so the values have to be exactly the values they would have typed —
 * including the type conversion, which is the one thing that turns a control's
 * string into the integer a pipeline wants.
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { Field } from "@/components/ui/Field";
import { Failure, Loading } from "@/components/ui/states";
import {
  convert,
  initialDraft,
  PublishedForm,
  type Draft,
} from "@/features/catalog/components/PublishedForm";
import { useCatalog, useCatalogEntry } from "@/features/catalog/useCatalog";
import { RecurrenceEditor } from "@/features/schedules/components/RecurrenceEditor";
import {
  compose,
  DEFAULT_DRAFT,
  localZone,
  type RecurrenceDraft,
} from "@/features/schedules/recurrence";
import { useCreateSchedule } from "@/features/schedules/useSchedules";
import type { CatchupPolicy, DstPolicy, OverlapPolicy } from "@/lib/api";
import { fieldErrors } from "@/lib/form";

const OVERLAP: { value: OverlapPolicy; label: string; detail: string }[] = [
  {
    value: "skip",
    label: "Skip this window",
    detail: "The window is dropped and recorded. Nothing queues up behind a slow run.",
  },
  {
    value: "queue",
    label: "Wait, then run it",
    detail: "The window keeps its place and starts when the previous run finishes.",
  },
  {
    value: "allow",
    label: "Start it anyway",
    detail: "Both run at once. Only sensible when the work does not share anything.",
  },
];

const CATCHUP: { value: CatchupPolicy; label: string; detail: string }[] = [
  {
    value: "skip_missed",
    label: "Skip them",
    detail: "Carry on from the next window. What was missed is recorded, not run.",
  },
  {
    value: "run_once",
    label: "Run once, now",
    detail: "Whatever was missed becomes a single catch-up run.",
  },
  {
    value: "run_all",
    label: "Run every one",
    detail: "One run per missed window. A week of downtime is a week of runs.",
  },
];

export function NewScheduleScreen() {
  const router = useRouter();
  const catalog = useCatalog("");
  const create = useCreateSchedule();

  const [slug, setSlug] = useState("");
  const [title, setTitle] = useState("");
  const [edits, setEdits] = useState<Draft>({});
  const [touched, setTouched] = useState(false);
  const [recurrence, setRecurrence] = useState<RecurrenceDraft>(DEFAULT_DRAFT);
  // Their zone, not UTC: "02:00" means somebody's 02:00.
  const [timezone, setTimezone] = useState(localZone);
  const [dstPolicy, setDstPolicy] = useState<DstPolicy>("skip_nonexistent");
  const [overlapPolicy, setOverlapPolicy] = useState<OverlapPolicy>("skip");
  const [catchupPolicy, setCatchupPolicy] = useState<CatchupPolicy>("skip_missed");

  const entry = useCatalogEntry(slug);
  const fields = useMemo(() => (slug ? (entry.data?.fields ?? []) : []), [slug, entry.data]);
  const draft = useMemo<Draft>(() => ({ ...initialDraft(fields), ...edits }), [fields, edits]);
  const { values, problems } = convert(fields, draft);
  const composed = compose(recurrence);
  const serverProblems = fieldErrors(create.error, [
    ...fields.map((field) => `values.${field.key}`),
    "title",
    "rrule",
  ]);

  const blocked =
    !slug || !title.trim() || Object.keys(problems).length > 0 || composed.rrule === null;

  function submit() {
    setTouched(true);
    if (blocked || !composed.rrule) return;
    create.mutate(
      {
        slug,
        title: title.trim(),
        values,
        rrule: composed.rrule,
        timezone,
        dstPolicy,
        catchupPolicy,
        overlapPolicy,
        maxConcurrentRuns: 1,
      },
      { onSuccess: (created) => router.push(`/schedules/${created.id}`) },
    );
  }

  if (catalog.isPending) return <Loading what="the catalog" />;
  if (catalog.isError) {
    return <Failure error={catalog.error} onRetry={() => void catalog.refetch()} />;
  }

  const entries = catalog.data.items;

  return (
    <div className="stack">
      <header className="page-header">
        <div>
          <h1>New schedule</h1>
          <p className="muted">
            Every window becomes an ordinary run — the same one you would start by hand.
          </p>
        </div>
        <Link href="/schedules" className="button button--quiet">
          Cancel
        </Link>
      </header>

      <form
        className="stack"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <section className="panel stack">
          <h2>What to run</h2>
          {entries.length === 0 ? (
            <p className="muted">
              Nothing is published yet, so there is nothing to schedule. An administrator
              publishes a catalog entry first.
            </p>
          ) : (
            <Field id="entry" label="Catalog entry">
              {(props) => (
                <select
                  {...props}
                  value={slug}
                  onChange={(event) => {
                    setSlug(event.target.value);
                    // The new entry has its own fields; keeping edits keyed by
                    // the old ones would carry a value onto a field that only
                    // happens to share a name.
                    setEdits({});
                    setTouched(false);
                  }}
                >
                  <option value="">Choose an entry…</option>
                  {entries.map((item) => (
                    // The slug too: two entries can share a title, and the
                    // one a schedule pins is not a detail to guess at.
                    <option key={item.slug} value={item.slug}>
                      {item.title} ({item.slug})
                    </option>
                  ))}
                </select>
              )}
            </Field>
          )}

          <Field
            id="title"
            label="Name this schedule"
            hint="What it is for, in your own words — this is what the list shows."
            error={serverProblems.for("title")}
          >
            {(props) => (
              <input
                {...props}
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                placeholder="Nightly growth rates"
              />
            )}
          </Field>
        </section>

        {slug ? (
          <section className="panel stack">
            <h2>Values</h2>
            <p className="muted">
              Filled in once, and used for every run. Nobody will be here to correct them.
            </p>
            {entry.isPending ? <Loading what="this entry" /> : null}
            {entry.isError ? <Failure error={entry.error} /> : null}
            {entry.data ? (
              <PublishedForm
                fields={fields}
                draft={draft}
                onChange={(key, value) =>
                  setEdits((previous) => ({ ...previous, [key]: value }))
                }
                errorFor={(key) =>
                  (touched ? problems[key] : undefined) ?? serverProblems.for(`values.${key}`)
                }
              />
            ) : null}
          </section>
        ) : null}

        <section className="panel stack">
          <h2>When</h2>
          <RecurrenceEditor
            draft={recurrence}
            onChange={setRecurrence}
            timezone={timezone}
            onTimezone={setTimezone}
            dstPolicy={dstPolicy}
            onDstPolicy={setDstPolicy}
          />
        </section>

        <section className="panel stack">
          <h2>If something is already running</h2>
          <Field id="overlap" label="When the previous run has not finished">
            {(props) => (
              <select
                {...props}
                value={overlapPolicy}
                onChange={(event) => setOverlapPolicy(event.target.value as OverlapPolicy)}
              >
                {OVERLAP.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <p className="muted">{OVERLAP.find((o) => o.value === overlapPolicy)?.detail}</p>

          <Field
            id="catchup"
            label="When windows passed while nothing was scheduling"
            hint="Only after an outage. A schedule that is merely a little late always runs."
          >
            {(props) => (
              <select
                {...props}
                value={catchupPolicy}
                onChange={(event) => setCatchupPolicy(event.target.value as CatchupPolicy)}
              >
                {CATCHUP.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <p className="muted">{CATCHUP.find((o) => o.value === catchupPolicy)?.detail}</p>
        </section>

        {create.isError && serverProblems.unattached.length > 0 ? (
          <div className="form__error" role="alert">
            {serverProblems.unattached.map((message) => (
              <p key={message}>{message}</p>
            ))}
          </div>
        ) : null}

        <div className="button-row">
          <button
            type="submit"
            className="button button--primary"
            disabled={create.isPending || entries.length === 0}
          >
            {create.isPending ? "Creating…" : "Create schedule"}
          </button>
          {touched && blocked ? (
            <span className="muted">
              {composed.problem ?? "Fill in everything above before creating this."}
            </span>
          ) : null}
        </div>
      </form>
    </div>
  );
}
