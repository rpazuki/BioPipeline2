"use client";

/**
 * Author a pipeline document, see what it compiles to, then store it.
 *
 * **The editor does not validate YAML itself.** A browser-side schema check
 * would be a second implementation of the compiler's rules, and the moment the
 * two disagree the author believes the wrong one. The server compiles; this
 * shows what it said. That costs a round trip and buys one source of truth —
 * the same reason the compiler collects every diagnostic rather than raising
 * on the first.
 *
 * Compiling is explicit rather than on every keystroke: compilation is real
 * work on a shared machine, and a half-typed document produces noise.
 */

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Field } from "@/components/ui/Field";
import { Failure } from "@/components/ui/states";
import { CompiledPreview } from "@/features/pipelines/components/CompiledPreview";
import { Diagnostics } from "@/features/pipelines/components/Diagnostics";
import { useCompilePreview, useCreateRevision } from "@/features/pipelines/usePipelines";
import { fieldErrors } from "@/lib/form";

/**
 * A document that compiles as it stands.
 *
 * An empty textarea is a worse starting point than a working example, and a
 * starter that errors on its first compile is worse than both: the author
 * cannot tell whether they broke it or it arrived broken.
 */
const STARTER = `pipeline: my_pipeline
title: My pipeline
defaults:
  data_root: $WILL_PROVIDE$
  threads: 4
inputs:
  data_root:
    accept: directory
    sources: [shared]
stages:
  - name: analyse
    steps:
      - name: load
        package: labUtils.demo
        method: run
        parameters:
          root: "{data_root}"
          n: "{threads}"
    outputs:
      report:
        path: "outputs/report.txt"
        delivery: [download]
`;

export function PipelineEditorScreen() {
  const router = useRouter();
  const [source, setSource] = useState(STARTER);
  const [title, setTitle] = useState("");
  const preview = useCompilePreview();
  const create = useCreateRevision();

  // A revision is immutable and permanent; storing one that has never
  // compiled in front of the author is how a broken pipeline gets published
  // and discovered at run time.
  const compiled = preview.data?.ok === true;
  // `variables` is the document the last compile actually saw. Comparing it to
  // the textarea is what stops "Create revision" from storing something nobody
  // has ever compiled, after an edit made between the two clicks.
  const stale = compiled && preview.variables !== source;

  const problems = fieldErrors(create.error, ["source_text", "title"]);

  return (
    <div className="stack">
      <header className="page-header">
        <h1>New pipeline revision</h1>
      </header>

      <div className="editor-layout">
        <section className="panel">
          <Field
            id="title"
            label="Title"
            hint="Optional. Names the pipeline the first time it is created."
            error={problems.for("title")}
          >
            {(props) => (
              <input
                {...props}
                type="text"
                value={title}
                onChange={(event) => setTitle(event.target.value)}
              />
            )}
          </Field>

          <Field
            id="source_text"
            label="Pipeline document"
            hint="YAML. Validated by the server's compiler, not in the browser."
            error={problems.for("source_text")}
          >
            {(props) => (
              <textarea
                {...props}
                className="editor"
                spellCheck={false}
                rows={24}
                value={source}
                onChange={(event) => setSource(event.target.value)}
              />
            )}
          </Field>

          <div className="button-row">
            <button
              type="button"
              className="button"
              onClick={() => preview.mutate(source)}
              disabled={preview.isPending}
            >
              {preview.isPending ? "Compiling…" : "Compile"}
            </button>
            <button
              type="button"
              className="button button--primary"
              disabled={!compiled || stale || create.isPending}
              onClick={() =>
                create.mutate(
                  { sourceText: source, ...(title ? { title } : {}) },
                  {
                    onSuccess: (revision) => router.push(`/pipelines/${revision.pipeline_id}`),
                  },
                )
              }
              title={
                compiled
                  ? stale
                    ? "The document changed since it was compiled."
                    : undefined
                  : "Compile the document first."
              }
            >
              {create.isPending ? "Saving…" : "Create revision"}
            </button>
          </div>

          {stale ? (
            <p className="muted">
              The document has changed since it was compiled. Compile again before saving.
            </p>
          ) : null}

          {problems.unattached.length > 0 ? (
            <div className="form__error" role="alert">
              {problems.unattached.map((message) => (
                <p key={message}>{message}</p>
              ))}
            </div>
          ) : null}
        </section>

        <div className="stack">
          {preview.isError ? <Failure error={preview.error} /> : null}
          {preview.data ? <Diagnostics items={preview.data.diagnostics ?? []} /> : null}
          {preview.data?.ok ? <CompiledPreview preview={preview.data} /> : null}
          {!preview.data && !preview.isError ? (
            <div className="panel">
              <p className="muted">
                Compile the document to see its inputs, its stage graph, and every problem the
                compiler found.
              </p>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
