"use client";

/**
 * A pipeline's revisions, and a way to run one.
 *
 * The submission form here takes raw JSON values, which is not the researcher
 * experience the plan describes — that one renders typed controls from a
 * publication's field specs, and publications are not in the API yet. This is
 * the admin's path: enough to run a revision you just authored and see what it
 * does. It is deliberately not dressed up as the researcher form.
 */

import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { DataTable, type Column } from "@/components/ui/DataTable";
import { Dialog } from "@/components/ui/Dialog";
import { Field } from "@/components/ui/Field";
import { Empty, Failure, Loading } from "@/components/ui/states";
import { usePipelineRevisions, useSubmitRun } from "@/features/pipelines/usePipelines";
import type { RevisionResponse } from "@/lib/api";
import { fieldErrors } from "@/lib/form";
import { shortId } from "@/lib/format";

function newIdempotencyKey(): string {
  return crypto.randomUUID();
}

export function PipelineDetailScreen({ pipelineId }: { pipelineId: string }) {
  const router = useRouter();
  const query = usePipelineRevisions(pipelineId);
  const submit = useSubmitRun();

  const [chosen, setChosen] = useState<RevisionResponse | null>(null);
  const [valuesText, setValuesText] = useState("{}");

  /**
   * One key per open dialog, not one per click.
   *
   * A retry after a dropped connection has to carry the *same* key or the run
   * starts twice, and on this hardware a second RNA-seq alignment is a day of
   * compute nobody asked for.
   */
  const idempotencyKey = useMemo(() => (chosen ? newIdempotencyKey() : ""), [chosen]);

  let parsed: Record<string, unknown> | null = null;
  let parseError: string | undefined;
  try {
    const candidate: unknown = JSON.parse(valuesText || "{}");
    if (typeof candidate !== "object" || candidate === null || Array.isArray(candidate)) {
      parseError = "Values must be a JSON object.";
    } else {
      parsed = candidate as Record<string, unknown>;
    }
  } catch {
    parseError = "This is not valid JSON.";
  }

  const problems = fieldErrors(submit.error, ["values", "pipeline_revision_id"]);

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
        <button
          type="button"
          className="button"
          onClick={() => {
            setValuesText("{}");
            setChosen(revision);
          }}
        >
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
        <Field
          id="values"
          label="Submitted values"
          hint="A JSON object. Typed forms arrive with publications."
          error={parseError ?? problems.for("values")}
        >
          {(props) => (
            <textarea
              {...props}
              className="editor"
              rows={10}
              spellCheck={false}
              value={valuesText}
              onChange={(event) => setValuesText(event.target.value)}
            />
          )}
        </Field>

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
            disabled={!parsed || submit.isPending}
            onClick={() => {
              if (!chosen || !parsed) return;
              submit.mutate(
                {
                  revisionId: chosen.revision_id,
                  values: parsed,
                  idempotencyKey,
                },
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
