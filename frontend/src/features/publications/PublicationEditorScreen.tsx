"use client";

/**
 * Compose a catalog entry from a compiled pipeline revision.
 *
 * Publishing is treated like releasing a version: pick a revision, choose what
 * to expose, name it in the words researchers use, **look at the form it
 * produces**, and only then open it. The preview is the point — it is the same
 * component the catalog renders, so what is shown here is what a researcher
 * gets, not an approximation of it.
 *
 * The editor cannot compose an invalid binding: the targets come from the
 * revision itself, under the same rules the publish validates against. What it
 * can still get wrong is editorial — an unhelpful label, the wrong type — and
 * that is what the preview is for.
 */

import { useRouter } from "next/navigation";
import Link from "next/link";
import { useMemo, useState } from "react";

import { Failure, Loading, StatusReport } from "@/components/ui/states";
import { usePublicationLibrary } from "./usePublicationLibrary";
import {
  PublishedForm,
  initialDraft as initialFormDraft,
} from "@/features/catalog/components/PublishedForm";
import { TargetEditor } from "@/features/publications/components/TargetEditor";
import {
  groupTargets,
  initialDraft,
  slugify,
  targetId,
  toFieldInputs,
  toPreviewFields,
  type FieldDraft,
} from "@/features/publications/model";
import {
  useBindableTargets,
  useCreatePublication,
  usePublishRevision,
} from "@/features/publications/usePublications";
import { usePipelineList, usePipelineRevisions } from "@/features/pipelines/usePipelines";
import { fieldErrors } from "@/lib/form";

export function PublicationEditorScreen() {
  const router = useRouter();
  const library = usePublicationLibrary();
  const pipelineList = usePipelineList();
  const [pipelineId, setPipelineId] = useState("");
  const revisions = usePipelineRevisions(pipelineId);
  const [revisionId, setRevisionId] = useState("");

  const bindable = useBindableTargets(revisionId || null);
  const targets = useMemo(() => bindable.data?.items ?? [], [bindable.data]);

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  // Only what the admin changed; the rest is derived from the targets, so a
  // refetch cannot replace a half-composed entry with the defaults again.
  const [edits, setEdits] = useState<Record<string, Partial<FieldDraft>>>({});

  const drafts = useMemo<Record<string, FieldDraft>>(() => {
    const composed: Record<string, FieldDraft> = {};
    for (const target of targets) {
      const id = targetId(target);
      composed[id] = { ...initialDraft(target), ...edits[id] };
    }
    return composed;
  }, [targets, edits]);

  const create = useCreatePublication();
  const publish = usePublishRevision();

  const composed = useMemo(() => {
    try {
      return {
        fields: toFieldInputs(targets, drafts),
        preview: toPreviewFields(targets, drafts, library.data),
        error: "",
      };
    } catch (error) {
      return { fields: [], preview: [], error: (error as Error).message };
    }
  }, [targets, drafts, library.data]);
  const fields = composed.fields;
  const previewFields = composed.preview;
  const previewDraft = useMemo(() => initialFormDraft(previewFields), [previewFields]);

  const problems = fieldErrors(create.error ?? publish.error, ["slug", "title"]);
  const slug = slugify(title);
  const usesLibrary = fields.some((field) => field.type_ref || field.preset_ref);
  const missingSelection =
    library.data &&
    fields.some(
      (field) =>
        (field.preset_ref && !library.data.presets[field.preset_ref]) ||
        (field.type_ref && !library.data.schemas[field.type_ref]),
    );
  const ready = Boolean(
    revisionId &&
    title.trim() &&
    slug &&
    !composed.error &&
    !missingSelection &&
    (!usesLibrary || library.data),
  );

  function update(id: string, next: Partial<FieldDraft>) {
    setEdits((previous) => ({ ...previous, [id]: { ...previous[id], ...next } }));
  }

  return (
    <div className="stack">
      <header className="page-header">
        <h1>New catalog entry</h1>
      </header>

      <section className="panel card card-body">
        <h2>1. Choose a pipeline revision</h2>
        <p className="muted">
          A revision is immutable, so an entry always offers exactly the graph that was
          compiled.
        </p>
        <div className="target__row">
          <div className="field">
            <label className="field__label form-label" htmlFor="pipeline">
              Pipeline
            </label>
            <select
              className="form-select"
              id="pipeline"
              value={pipelineId}
              onChange={(event) => {
                setPipelineId(event.target.value);
                setRevisionId("");
                setEdits({});
              }}
            >
              <option value="">Choose…</option>
              {(pipelineList.data?.items ?? []).map((pipeline) => (
                <option key={pipeline.id} value={pipeline.id}>
                  {pipeline.title}
                </option>
              ))}
            </select>
          </div>

          <div className="field">
            <label className="field__label form-label" htmlFor="revision">
              Revision
            </label>
            <select
              className="form-select"
              id="revision"
              value={revisionId}
              disabled={!pipelineId}
              onChange={(event) => {
                setRevisionId(event.target.value);
                setEdits({});
              }}
            >
              <option value="">Choose…</option>
              {(revisions.data?.items ?? []).map((revision) => (
                <option key={revision.revision_id} value={revision.revision_id}>
                  v{revision.version}
                </option>
              ))}
            </select>
          </div>
        </div>
      </section>

      {revisionId ? (
        <>
          <section className="panel card card-body">
            <h2>2. Describe the entry</h2>
            <div className="field">
              <label className="field__label form-label" htmlFor="title">
                Title
              </label>
              <input
                className="form-control"
                id="title"
                type="text"
                value={title}
                placeholder="What a researcher will look for"
                onChange={(event) => setTitle(event.target.value)}
              />
              {slug ? (
                <p className="field__hint">
                  Address: <code>/catalog/{slug}</code>
                </p>
              ) : null}
            </div>
            <div className="field">
              <label className="field__label form-label" htmlFor="description">
                Description
              </label>
              <textarea
                className="form-control"
                id="description"
                rows={2}
                value={description}
                onChange={(event) => setDescription(event.target.value)}
              />
            </div>
          </section>

          <section className="panel card card-body">
            <h2>3. Choose what to expose</h2>
            <p>
              Include a target to ask the researcher for it or supply a fixed value. Manage
              reusable definitions in the{" "}
              <Link href="/publications/library">types and presets library</Link>.
            </p>
            <button
              type="button"
              className="button btn"
              disabled={library.isFetching}
              onClick={() => {
                create.reset();
                publish.reset();
                void library.refetch();
              }}
            >
              Refresh types and presets
            </button>
            {missingSelection ? (
              <StatusReport
                tone="error"
                title="A selected type or preset was removed. Choose an available definition."
              />
            ) : null}
            {library.isError ? (
              <Failure error={library.error} onRetry={() => void library.refetch()} />
            ) : null}
            {composed.error ? <StatusReport tone="error" title={composed.error} /> : null}
            {bindable.isPending ? <Loading what="this revision" /> : null}
            {bindable.isError ? (
              <Failure error={bindable.error} onRetry={() => void bindable.refetch()} />
            ) : null}

            {groupTargets(targets).map((group) => (
              <div key={group.name} className="stack">
                <h3 className="form__group">{group.name}</h3>
                {group.detail ? <p className="muted">{group.detail}</p> : null}
                <ul className="target-list">
                  {group.targets.map((target) => {
                    const id = targetId(target);
                    return (
                      <TargetEditor
                        key={id}
                        id={id}
                        target={target}
                        draft={drafts[id]!}
                        library={library.data}
                        onChange={(next) => update(id, next)}
                      />
                    );
                  })}
                </ul>
              </div>
            ))}
          </section>

          <section className="panel card card-body">
            <h2>4. What a researcher will see</h2>
            <p className="muted">
              The catalog renders this component, so this is the form itself rather than an
              impression of it.
            </p>
            <div className="preview">
              <PublishedForm
                fields={previewFields}
                draft={previewDraft}
                onChange={() => {}}
                errorFor={() => undefined}
              />
            </div>
          </section>

          <section className="panel card card-body">
            <h2>5. Publish</h2>
            {problems.unattached.length > 0 ? (
              <div className="form__error" role="alert">
                {problems.unattached.map((message) => (
                  <p key={message}>{message}</p>
                ))}
              </div>
            ) : null}
            <div className="button-row">
              <button
                aria-busy={create.isPending || publish.isPending}
                type="button"
                className="button btn button--primary btn-primary"
                disabled={!ready || create.isPending || publish.isPending}
                onClick={() =>
                  create.mutate(
                    {
                      slug,
                      pipelineRevisionId: revisionId,
                      title: title.trim(),
                      ...(description.trim() ? { description: description.trim() } : {}),
                      fields,
                      ...(usesLibrary && library.data
                        ? { libraryDigest: library.data.digest }
                        : {}),
                    },
                    {
                      onSuccess: (created) =>
                        publish.mutate(
                          {
                            publicationId: created.publication_id,
                            revisionId: created.revision_id,
                          },
                          { onSuccess: () => router.push(`/catalog/${slug}`) },
                        ),
                    },
                  )
                }
              >
                {create.isPending || publish.isPending ? "Publishing…" : "Publish"}
              </button>
              <span className="muted">
                {ready ? `${fields.length} field(s)` : "Choose a revision and a title first."}
              </span>
            </div>
          </section>
        </>
      ) : null}
    </div>
  );
}
