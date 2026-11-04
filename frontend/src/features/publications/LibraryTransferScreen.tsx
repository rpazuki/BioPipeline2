"use client";

import Link from "next/link";
import { useState } from "react";
import { Failure, Loading, StatusReport } from "@/components/ui/states";
import {
  useImportLibrary,
  usePublicationLibrary,
  useSaveLibrary,
} from "./usePublicationLibrary";
import { mergeLibrarySource } from "./library-document";

export function LibraryTransferScreen() {
  const library = usePublicationLibrary(),
    importer = useImportLibrary(),
    save = useSaveLibrary();
  const [format, setFormat] = useState<"legacy_types" | "legacy_constants">("legacy_types");
  const [source, setSource] = useState("");
  const [preview, setPreview] = useState("");
  return (
    <div className="stack">
      <header className="page-header">
        <h1>Data transfer</h1>
        <Link className="btn" href="/publications/library">
          Types and presets
        </Link>
      </header>
      <section className="panel card card-body stack">
        <h2>Import from an earlier BioPipeline deployment</h2>
        <p>
          This optional tool converts shared definitions and values. It does not import complete
          jobs, publications, or researchers’ private saved values.
        </p>
        {library.isPending ? (
          <Loading what="current library" />
        ) : library.isError ? (
          <Failure error={library.error} />
        ) : (
          <>
            <label className="form-label">
              Source format
              <select
                className="form-select"
                value={format}
                onChange={(e) => {
                  setFormat(e.target.value as typeof format);
                  setPreview("");
                  importer.reset();
                }}
              >
                <option value="legacy_types">Earlier BioPipeline type definitions</option>
                <option value="legacy_constants">
                  Earlier BioPipeline shared defaults and choices
                </option>
              </select>
            </label>
            <p className="muted">
              {format === "legacy_types"
                ? "Paste the earlier project’s mapping of named type definitions."
                : "Paste an earlier job definition containing reusable defaults or named variants. A variant is a named alternative value."}
            </p>
            <label className="form-label">
              Source to import (YAML or JSON)
              <textarea
                className="form-control editor"
                rows={12}
                value={source}
                onChange={(e) => {
                  setSource(e.target.value);
                  setPreview("");
                }}
              />
            </label>
            <button
              type="button"
              className="btn btn-outline-primary align-start"
              disabled={!source.trim() || importer.isPending}
              onClick={() =>
                importer.mutate(
                  {
                    source_text: source,
                    base_source: library.data.source_text,
                    expected_digest: library.data.digest,
                    format,
                  },
                  {
                    onSuccess: (result) =>
                      setPreview(
                        mergeLibrarySource(library.data.source_text, result.source_text),
                      ),
                  },
                )
              }
            >
              Preview conversion
            </button>
            {importer.isError ? <Failure error={importer.error} /> : null}
            {preview ? (
              <>
                <label className="form-label">
                  Merged library preview
                  <textarea
                    className="form-control editor"
                    readOnly
                    rows={16}
                    value={preview}
                  />
                </label>
                <ul>
                  {importer.data?.notes.map((note, index) => (
                    <li key={index}>{note}</li>
                  ))}
                </ul>
                <button
                  type="button"
                  className="btn btn-primary align-start"
                  disabled={save.isPending}
                  aria-busy={save.isPending}
                  onClick={() =>
                    save.mutate(
                      { source_text: preview, expected_digest: importer.data!.base_digest },
                      { onSuccess: () => setPreview("") },
                    )
                  }
                >
                  Save reviewed conversion
                </button>
              </>
            ) : null}
            {save.isSuccess ? (
              <StatusReport tone="success" title="Converted library saved" />
            ) : null}
            {save.isError ? <Failure error={save.error} /> : null}
          </>
        )}
      </section>
    </div>
  );
}
