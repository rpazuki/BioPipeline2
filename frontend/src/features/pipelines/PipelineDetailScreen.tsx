"use client";

/**
 * A pipeline's revisions, and a way to run one.
 *
 * The submission form is generated from the revision's own compiled contract:
 * which values it wants, which are required, whether each is a path or a
 * value, and where a path may come from. All of that was decided by the
 * compiler when the revision was created, and a revision is immutable, so the
 * form cannot disagree with what will actually run.
 *
 * This is still the admin's path rather than the researcher's. The researcher
 * journey goes through a publication, which relabels and groups these fields
 * and decides which are exposed at all; publications are not in the API yet.
 * What is here is the underlying contract, unedited.
 */

import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { DataTable, type Column } from "@/components/ui/DataTable";
import { Dialog } from "@/components/ui/Dialog";
import { Empty, Failure, Loading } from "@/components/ui/states";
import {
  missing,
  SubmissionForm,
  type Values,
} from "@/features/pipelines/components/SubmissionForm";
import {
  usePipelineRevisions,
  useRevision,
  useSubmitRun,
} from "@/features/pipelines/usePipelines";
import type { RevisionResponse } from "@/lib/api";
import { fieldErrors } from "@/lib/form";
import { shortId } from "@/lib/format";

export function PipelineDetailScreen({ pipelineId }: { pipelineId: string }) {
  const router = useRouter();
  const query = usePipelineRevisions(pipelineId);
  const submit = useSubmitRun();

  const [chosen, setChosen] = useState<RevisionResponse | null>(null);
  const [values, setValues] = useState<Values>({});

  const contract = useRevision(chosen?.revision_id ?? null);
  const inputs = contract.data?.inputs ?? [];
  const outputs = contract.data?.outputs ?? [];

  /**
   * One key per open dialog, not one per click.
   *
   * A retry after a dropped connection has to carry the *same* key or the run
   * starts twice, and on this hardware a second RNA-seq alignment is a day of
   * compute nobody asked for.
   */
  const idempotencyKey = useMemo(() => (chosen ? crypto.randomUUID() : ""), [chosen]);

  const stillEmpty = missing(inputs, values);

  // The server reports a rejected value at `inputs.<key>`, so naming the
  // fields by key is enough for each message to land on its own input.
  const problems = fieldErrors(
    submit.error,
    inputs.map((input) => input.key),
  );

  function open(revision: RevisionResponse) {
    setValues({});
    submit.reset();
    setChosen(revision);
  }

  const columns: Column<RevisionResponse>[] = [
    { key: "version", header: "Version", render: (revision) => `v${revision.version}` },
    {
      key: "hash",
      header: "Graph hash",
      render: (revision) => <code>{revision.graph_hash.slice(0, 12)}</code>,
    },
    {
      key: "id",
      header: "Revision",
      render: (revision) => <code>{shortId(revision.revision_id)}</code>,
      secondary: true,
    },
    {
      key: "run",
      header: "",
      render: (revision) => (
        <button type="button" className="button" onClick={() => open(revision)}>
          Run…
        </button>
      ),
    },
  ];

  return (
    <div className="stack">
      <header className="page-header">
        <h1>Pipeline</h1>
        <code className="muted">{pipelineId}</code>
      </header>

      {query.isPending ? <Loading what="revisions" /> : null}
      {query.isError ? (
        <Failure error={query.error} onRetry={() => void query.refetch()} />
      ) : null}

      {query.data ? (
        query.data.items.length === 0 ? (
          <Empty title="This pipeline has no revisions." />
        ) : (
          <section className="panel">
            <h2>Revisions</h2>
            <p className="muted">
              A revision is immutable. Running one always runs exactly the graph that was
              compiled.
            </p>
            <DataTable
              caption="Revisions of this pipeline"
              rows={query.data.items}
              columns={columns}
              rowKey={(revision) => revision.revision_id}
            />
          </section>
        )
      ) : null}

      <Dialog
        open={chosen !== null}
        title={chosen ? `Run version ${chosen.version}` : "Run"}
        onClose={() => setChosen(null)}
      >
        {contract.isPending ? <Loading what="this revision's inputs" /> : null}
        {contract.isError ? (
          <Failure error={contract.error} onRetry={() => void contract.refetch()} />
        ) : null}

        {contract.data ? (
          <>
            <SubmissionForm
              inputs={inputs}
              values={values}
              onChange={(key, value) =>
                setValues((previous) => ({ ...previous, [key]: value }))
              }
              errorFor={problems.for}
            />

            {outputs.length > 0 ? (
              <details className="disclosure">
                <summary>What this produces</summary>
                <ul className="plain-list">
                  {outputs.map((output) => (
                    <li key={`${output.stage}.${output.key}`}>
                      <code>{output.key}</code>{" "}
                      <span className="muted">
                        {/* The stage, always: a matrix writes the same output
                            key once per row, to a different path each time, so
                            the key alone appears twice and names nothing. */}
                        from {output.stage} · {(output.delivery ?? []).join(", ")}
                        {output.shared_root ? ` → ${output.shared_root}` : ""}
                        {output.optional ? " · optional" : ""}
                      </span>
                    </li>
                  ))}
                </ul>
              </details>
            ) : null}
          </>
        ) : null}

        {problems.unattached.length > 0 ? (
          <div className="form__error" role="alert">
            {problems.unattached.map((message) => (
              <p key={message}>{message}</p>
            ))}
          </div>
        ) : null}

        <div className="dialog__actions">
          <button
            type="button"
            className="button button--quiet"
            onClick={() => setChosen(null)}
          >
            Cancel
          </button>
          <button
            type="button"
            className="button button--primary"
            disabled={!contract.data || stillEmpty.length > 0 || submit.isPending}
            title={stillEmpty.length > 0 ? `Still needed: ${stillEmpty.join(", ")}` : undefined}
            onClick={() => {
              if (!chosen) return;
              submit.mutate(
                { revisionId: chosen.revision_id, values, idempotencyKey },
                {
                  onSuccess: (result) => {
                    setChosen(null);
                    router.push(`/runs/${result.run_id}`);
                  },
                },
              );
            }}
          >
            {submit.isPending ? "Submitting…" : "Submit run"}
          </button>
        </div>
      </Dialog>
    </div>
  );
}
