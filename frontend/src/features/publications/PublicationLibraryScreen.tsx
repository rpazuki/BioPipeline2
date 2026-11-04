"use client";

import Link from "next/link";
import { useState } from "react";
import { Failure, Loading, StatusReport } from "@/components/ui/states";
import {
  usePublicationLibrary,
  useSaveLibrary,
  useValidateLibrary,
  useImportLibrary,
} from "./usePublicationLibrary";

const EXAMPLE = `definitions:
  WindowSize:
    type: integer
  ProcessingOptions:
    fields:
      window: {type: integer, required: true}
      normalize: {type: boolean, default: true}
  ProcessingChoice:
    type: enum
    options:
      - label: Standard
        value: {window: 5, normalize: true}
      - label: Wide window
        value: {window: 11, normalize: true}
presets:
  standard_window:
    type_ref: WindowSize
    value: 5
  standard_options:
    type_ref: ProcessingOptions
    value: {window: 5, normalize: true}
`;

export function PublicationLibraryScreen() {
  const library = usePublicationLibrary();
  const validate = useValidateLibrary();
  const save = useSaveLibrary();
  const importer = useImportLibrary();
  const [importSource, setImportSource] = useState("");
  const [importFormat, setImportFormat] = useState<
    "legacy_types" | "legacy_constants" | "presets"
  >("legacy_types");
  const [editing, setEditing] = useState<{ source: string; digest: string } | null>(null);
  const source = editing?.source ?? library.data?.source_text ?? "";
  const validated = validate.data?.source_text === source;
  const busy = validate.isPending || save.isPending || importer.isPending;

  function edit(next: string) {
    importer.reset();
    setEditing({ source: next, digest: editing?.digest ?? library.data!.digest });
    validate.reset();
    save.reset();
  }

  return (
    <div className="stack">
      <header className="page-header">
        <h1>Publication library</h1>
        <Link href="/publications" className="button btn">
          Publications
        </Link>
      </header>
      <p>
        Define reusable types and named values here, then select them when publishing a
        pipeline. A preset can become an editable default or a fixed value. Existing
        publications keep their saved definitions.
      </p>
      {library.isPending ? <Loading what="publication library" /> : null}
      {library.isError ? (
        <Failure error={library.error} onRetry={() => void library.refetch()} />
      ) : null}
      {library.data ? (
        <section className="panel card card-body stack">
          <details>
            <summary>Import existing types or named values</summary>
            <label className="field__label form-label" htmlFor="library-import-format">
              Import format
            </label>
            <select
              id="library-import-format"
              className="form-select"
              value={importFormat}
              onChange={(event) => setImportFormat(event.target.value as typeof importFormat)}
            >
              <option value="legacy_types">Old project type library</option>
              <option value="legacy_constants">Old job defaults and named variants</option>
              <option value="presets">Named presets with type references</option>
            </select>
            <label className="field__label form-label" htmlFor="library-import-source">
              Source to import (YAML or JSON)
            </label>
            <textarea
              id="library-import-source"
              className="form-control"
              rows={7}
              value={importSource}
              onChange={(event) => setImportSource(event.target.value)}
            />
            <button
              type="button"
              className="button btn"
              disabled={busy || importer.isPending || !importSource.trim()}
              aria-busy={importer.isPending}
              onClick={() =>
                importer.mutate(
                  {
                    source_text: importSource,
                    base_source: source,
                    expected_digest: editing?.digest ?? library.data.digest,
                    format: importFormat,
                  },
                  {
                    onSuccess: (preview) => {
                      setEditing({ source: preview.source_text, digest: preview.base_digest });
                      validate.reset();
                      save.reset();
                    },
                  },
                )
              }
            >
              Preview merge into editor
            </button>
            {importer.isError ? <Failure error={importer.error} /> : null}
            {importer.data ? (
              <StatusReport
                tone="warning"
                title="Import loaded into editor. Review, validate and save it."
              >
                {importer.data.notes.map((note) => (
                  <p key={note}>{note}</p>
                ))}
              </StatusReport>
            ) : null}
          </details>
          <label className="field__label form-label" htmlFor="publication-library-source">
            Types and presets (YAML)
          </label>
          <textarea
            className="form-control code-editor"
            id="publication-library-source"
            rows={24}
            value={source}
            disabled={busy}
            onChange={(event) => edit(event.target.value)}
          />
          <div className="button-row">
            <button className="button btn" disabled={busy} onClick={() => edit(EXAMPLE)}>
              Load example into editor
            </button>
            <button
              className="button btn"
              disabled={busy}
              aria-busy={validate.isPending}
              onClick={() => validate.mutate(source)}
            >
              Validate
            </button>
            <button
              className="button btn btn-primary"
              disabled={!validated || busy}
              aria-busy={save.isPending}
              onClick={() =>
                save.mutate(
                  {
                    source_text: source,
                    expected_digest: editing?.digest ?? library.data.digest,
                  },
                  {
                    onSuccess: () => setEditing(null),
                  },
                )
              }
            >
              Save library
            </button>
          </div>
          {validate.isError ? <Failure error={validate.error} /> : null}
          {save.isError ? (
            <>
              <Failure error={save.error} />
              <button
                className="button btn"
                onClick={() => {
                  setEditing(null);
                  validate.reset();
                  save.reset();
                  void library.refetch();
                }}
              >
                Discard edits and reload
              </button>
            </>
          ) : null}
          {validated ? (
            <StatusReport tone="success" title="Library is valid">
              {Object.keys(validate.data!.schemas).length} types and{" "}
              {Object.keys(validate.data!.presets).length} presets.
            </StatusReport>
          ) : null}
          {save.isSuccess ? (
            <StatusReport tone="success" title="Publication library saved" />
          ) : null}
        </section>
      ) : null}
      <details className="panel card card-body">
        <summary>Example and usage</summary>
        <p>
          WindowSize is a named integer type. standard_window supplies its value, 5.
          ProcessingOptions describes an object with two named fields. ProcessingChoice presents
          labelled choices that return complete objects.
        </p>
        <pre>{EXAMPLE}</pre>
        <p>
          Open New entry on the Publications page, select a target, and choose its type or
          preset. Choose Fixed value to hide a constant from the researcher form.
        </p>
      </details>
    </div>
  );
}
