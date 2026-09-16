"use client";

/**
 * One catalog entry, and the form that starts it.
 *
 * The researcher journey ends here: fill in the admin's fields, confirm, and
 * land on the run. Nothing on this page names a stage, a step, a parameter or
 * a pipeline revision — a publication exists precisely so none of that is a
 * researcher's problem.
 */

import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { Dialog } from "@/components/ui/Dialog";
import { Failure, Loading } from "@/components/ui/states";
import {
  convert,
  initialDraft,
  PublishedForm,
  type Draft,
} from "@/features/catalog/components/PublishedForm";
import { useCatalogEntry, useSubmitFromCatalog } from "@/features/catalog/useCatalog";
import { fieldErrors } from "@/lib/form";

export function CatalogEntryScreen({ slug }: { slug: string }) {
  const router = useRouter();
  const entry = useCatalogEntry(slug);
  const submit = useSubmitFromCatalog(slug);

  // Only what the person changed. The form's starting state is derived from
  // the entry rather than copied into state, so a refetch cannot silently
  // replace a half-filled form with the defaults again.
  const [edits, setEdits] = useState<Draft>({});
  const [confirming, setConfirming] = useState(false);
  const [touched, setTouched] = useState(false);

  const fields = useMemo(() => entry.data?.fields ?? [], [entry.data]);
  const draft = useMemo<Draft>(() => ({ ...initialDraft(fields), ...edits }), [fields, edits]);

  const { values, problems } = convert(fields, draft);
  const serverProblems = fieldErrors(
    submit.error,
    fields.map((field) => `values.${field.key}`),
  );

  /**
   * One key per confirmation, not per click.
   *
   * A retry after a dropped connection has to carry the same key, or a day of
   * alignment runs twice.
   */
  const idempotencyKey = useMemo(() => (confirming ? crypto.randomUUID() : ""), [confirming]);

  if (entry.isPending) return <Loading what="this catalog entry" />;
  if (entry.isError) {
    return <Failure error={entry.error} onRetry={() => void entry.refetch()} />;
  }

  function errorFor(key: string): string | undefined {
    // Client-side problems only after the first attempt: telling somebody a
    // field is required before they have touched the form is nagging.
    return (touched ? problems[key] : undefined) ?? serverProblems.for(`values.${key}`);
  }

  const blocked = Object.keys(problems).length > 0;

  return (
    <div className="stack">
      <header className="page-header">
        <div>
          <h1>{entry.data.title}</h1>
          {entry.data.description ? <p className="muted">{entry.data.description}</p> : null}
        </div>
        <span className="muted">version {entry.data.version}</span>
      </header>

      <section className="panel">
        <form
          className="form"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            setTouched(true);
            if (!blocked) setConfirming(true);
          }}
        >
          <PublishedForm
            fields={fields}
            draft={draft}
            onChange={(key, value) => setEdits((previous) => ({ ...previous, [key]: value }))}
            errorFor={errorFor}
          />

          {serverProblems.unattached.length > 0 ? (
            <div className="form__error" role="alert">
              {serverProblems.unattached.map((message) => (
                <p key={message}>{message}</p>
              ))}
            </div>
          ) : null}

          <button type="submit" className="button button--primary">
            Review and start
          </button>
        </form>
      </section>

      <Dialog open={confirming} title="Start this run?" onClose={() => setConfirming(false)}>
        {/* A confirmation that repeats the values back, because this may be a
            day of compute and a mistyped path is cheaper to catch here. */}
        <p className="muted">
          {entry.data.title}, version {entry.data.version}.
        </p>
        {fields.length === 0 ? (
          <p>This entry takes no values.</p>
        ) : (
          <dl className="detail-list">
            {fields.map((field) => (
              <div key={field.key} className="detail-list__pair">
                <dt>{field.label}</dt>
                <dd>
                  {values[field.key] === undefined ? (
                    <span className="muted">not set</span>
                  ) : (
                    <code>{JSON.stringify(values[field.key])}</code>
                  )}
                </dd>
              </div>
            ))}
          </dl>
        )}

        {submit.isError ? <Failure error={submit.error} /> : null}

        <div className="dialog__actions">
          <button
            type="button"
            className="button button--quiet"
            onClick={() => setConfirming(false)}
          >
            Go back
          </button>
          <button
            type="button"
            className="button button--primary"
            disabled={submit.isPending}
            onClick={() =>
              submit.mutate(
                { values, idempotencyKey },
                {
                  onSuccess: (result) => {
                    setConfirming(false);
                    router.push(`/runs/${result.run_id}`);
                  },
                  onError: () => setConfirming(false),
                },
              )
            }
          >
            {submit.isPending ? "Starting…" : "Start run"}
          </button>
        </div>
      </Dialog>
    </div>
  );
}
