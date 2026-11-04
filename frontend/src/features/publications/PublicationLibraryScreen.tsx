"use client";

import Link from "next/link";
import { Dialog } from "@/components/ui/Dialog";
import { useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useApi } from "@/features/auth/session";
import { Failure, Loading, StatusReport } from "@/components/ui/states";
import { TypedField, type TypeSchema } from "@/features/values/TypedField";
import {
  changeLibrary,
  libraryDocument,
  mapping,
  mergeLibrarySource,
  moveField,
  previewSchema,
  renameLibraryKey,
} from "./library-document";
import { TypeExtraction } from "./TypeExtraction";
import { TypeDefinitionEditor } from "./TypeDefinitionEditor";
import {
  usePublicationLibrary,
  useSaveLibrary,
  useValidateLibrary,
  useImportLibrary,
} from "./usePublicationLibrary";

export const LIBRARY_EXAMPLE = `definitions:
  WindowSize:
    type: integer
    label: Window size
    nullable: false
  ProcessingOptions:
    label: Processing options
    fields:
      window: {type: integer, required: true, nullable: false, help: Number of consecutive items}
      enabled: {type: boolean, default: true, nullable: false}
  ProcessingChoice:
    type: enum
    options:
      - label: Standard
        value: {window: 5, enabled: true}
      - label: Wide window
        value: {window: 11, enabled: true}
presets:
  standard_options:
    type_ref: ProcessingOptions
    value: {window: 5, enabled: true}
`;

export function PublicationLibraryScreen() {
  const client = useApi();
  const library = usePublicationLibrary();
  const validate = useValidateLibrary();
  const save = useSaveLibrary();
  const importer = useImportLibrary();
  const form = useRef<HTMLFormElement>(null);
  const [editing, setEditing] = useState<{ source: string; digest: string } | null>(null);
  const [section, setSection] = useState<"definitions" | "presets">("definitions");
  const [mode, setMode] = useState<"visual" | "yaml" | "usage">("visual");
  const [selection, select] = useState("");
  const [search, setSearch] = useState("");
  const [shape, setShape] = useState("single");
  const [preview, setPreview] = useState<unknown>(undefined);
  const [importSource, setImportSource] = useState("");
  const [localError, setLocalError] = useState("");
  const [confirmation, setConfirmation] = useState<"example" | "remove" | "reload" | null>(
    null,
  );
  const source =
    editing?.source ?? library.data?.source_text ?? "definitions: {}\npresets: {}\n";
  const parsed = useMemo(() => {
    try {
      return { data: mapping(libraryDocument(source).toJS()), error: "" };
    } catch (error) {
      return { data: {}, error: String(error) };
    }
  }, [source]);
  const definitions = mapping(parsed.data.definitions);
  const storedEntries = useMemo(() => {
    try {
      return mapping(
        mapping(
          libraryDocument(library.data?.source_text ?? "definitions: {}\npresets: {}\n").toJS(),
        )[section],
      );
    } catch {
      return {};
    }
  }, [library.data, section]);
  const entries = mapping(parsed.data[section]);
  const key = Object.hasOwn(entries, selection) ? selection : (Object.keys(entries)[0] ?? "");
  const entry = mapping(entries[key]);
  const busy = validate.isPending || save.isPending || importer.isPending;
  const usages = useQuery({
    queryKey: ["publication-library-usage"],
    queryFn: () =>
      client.get<{ slug: string; title: string; types: string[]; presets: string[] }[]>(
        "/publication-library/usage",
      ),
    enabled: mode === "usage",
  });
  let schema: TypeSchema | undefined;
  let previewError = "";
  try {
    if (key)
      schema = previewSchema(
        section === "definitions" ? key : String(entry.type_ref),
        definitions,
      );
  } catch (error) {
    previewError = String(error);
  }
  function edit(update: string | ((current: string) => string)) {
    setEditing((current) => ({
      source:
        typeof update === "string"
          ? update
          : update(current?.source ?? library.data!.source_text),
      digest: current?.digest ?? library.data!.digest,
    }));
    validate.reset();
    save.reset();
    setLocalError("");
  }
  const change = (path: string[], value: unknown) =>
    edit((current) => changeLibrary(current, path, value));
  const remove = (path: string[]) =>
    edit((current) => changeLibrary(current, path, undefined, true));
  function create() {
    let name = section === "definitions" ? "NewType" : "new_preset";
    while (Object.hasOwn(entries, name)) name += "_";
    change(
      [section, name],
      section === "definitions"
        ? {
            label: "New type",
            fields: { value: { type: "string", nullable: false, required: true } },
          }
        : { type_ref: Object.keys(definitions)[0] ?? "", value: {} },
    );
    select(name);
    setMode("visual");
    setPreview(undefined);
  }
  function saveCurrent() {
    if (!form.current?.reportValidity() || parsed.error) return;
    save.mutate(
      { source_text: source, expected_digest: editing?.digest ?? library.data!.digest },
      { onSuccess: () => setEditing(null) },
    );
  }
  return (
    <div className="stack">
      <header className="page-header">
        <div>
          <h1>Types and presets</h1>
          <p className="muted">Reusable definitions and shared values for publication.</p>
        </div>
        <Link href="/publications" className="btn">
          Publications
        </Link>
      </header>
      {library.isPending ? (
        <Loading what="publication library" />
      ) : library.isError ? (
        <Failure error={library.error} />
      ) : null}
      {library.data ? (
        <form
          ref={form}
          onSubmit={(e) => {
            e.preventDefault();
            saveCurrent();
          }}
          className="stack"
        >
          <fieldset disabled={busy} className="stack">
            <div className="button-row">
              <div className="btn-group" role="group" aria-label="Library section">
                <button
                  type="button"
                  aria-pressed={section === "definitions"}
                  className={`btn ${section === "definitions" ? "btn-primary" : "btn-outline-secondary"}`}
                  onClick={() => {
                    setSection("definitions");
                    select("");
                    setPreview(undefined);
                  }}
                >
                  Types
                </button>
                <button
                  type="button"
                  aria-pressed={section === "presets"}
                  className={`btn ${section === "presets" ? "btn-primary" : "btn-outline-secondary"}`}
                  onClick={() => {
                    setSection("presets");
                    select("");
                    setPreview(undefined);
                  }}
                >
                  Shared presets
                </button>
              </div>
              <button
                type="button"
                className="btn btn-outline-primary"
                disabled={busy || !!parsed.error}
                onClick={create}
              >
                New {section === "definitions" ? "type" : "preset"}
              </button>
              <details className="library-more">
                <summary>More</summary>
                <div className="panel card card-body stack">
                  <button
                    type="button"
                    className="btn"
                    onClick={() => setConfirmation("example")}
                  >
                    Load example
                  </button>
                  <label className="form-label">
                    Presets to import (YAML)
                    <textarea
                      className="form-control"
                      rows={4}
                      value={importSource}
                      onChange={(e) => setImportSource(e.target.value)}
                    />
                  </label>
                  <button
                    type="button"
                    className="btn"
                    disabled={busy || !importSource.trim()}
                    onClick={() =>
                      importer.mutate(
                        {
                          format: "presets",
                          source_text: importSource,
                          base_source: source,
                          expected_digest: editing?.digest ?? library.data!.digest,
                        },
                        {
                          onSuccess: (data) => {
                            edit(mergeLibrarySource(source, data.source_text));
                            setSection("presets");
                          },
                        },
                      )
                    }
                  >
                    Preview preset import
                  </button>
                  <TypeExtraction
                    source={source}
                    onMerge={(next) => {
                      edit(next);
                      setSection("definitions");
                    }}
                  />
                  <Link href="/admin/data-transfer">
                    Transfer definitions from an earlier BioPipeline deployment
                  </Link>
                </div>
              </details>
            </div>
            <div className="library-workspace library-workspace--focused">
              <aside className="library-list stack stack--compact">
                <label className="form-label">
                  Find {section === "definitions" ? "a type" : "a preset"}
                  <input
                    className="form-control"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Search by name"
                  />
                </label>
                {Object.entries(entries)
                  .filter(([name, value]) =>
                    `${name} ${mapping(value).label || ""}`
                      .toLowerCase()
                      .includes(search.toLowerCase()),
                  )
                  .map(([name, value]) => (
                    <button
                      type="button"
                      key={name}
                      className={`btn library-list__entry ${name === key ? "btn-primary" : "btn-outline-secondary"}`}
                      onClick={() => {
                        if (form.current?.reportValidity() === false) return;
                        select(name);
                        setPreview(undefined);
                      }}
                    >
                      <span>{String(mapping(value).label || name)}</span>
                      <small>{name}</small>
                    </button>
                  ))}
                {!Object.keys(entries).length ? (
                  <p className="muted">
                    Create your first {section === "definitions" ? "type" : "preset"}, or load
                    the example under More.
                  </p>
                ) : null}
              </aside>
              <section className="panel card card-body stack library-detail">
                <div className="page-header">
                  <div>
                    <h2>{String(entry.label || key || "Library")}</h2>
                    {key ? <code>{key}</code> : null}
                  </div>
                  <div className="btn-group" role="group" aria-label="Editor view">
                    {["visual", "yaml", "usage"].map((view) => (
                      <button
                        key={view}
                        type="button"
                        className={`btn ${mode === view ? "btn-primary" : "btn-outline-secondary"}`}
                        aria-pressed={mode === view}
                        onClick={() => {
                          if (mode !== "visual" || form.current?.reportValidity())
                            setMode(view as typeof mode);
                        }}
                      >
                        {view === "visual" ? "Visual" : view === "yaml" ? "YAML" : "Used by"}
                      </button>
                    ))}
                  </div>
                </div>
                {mode === "yaml" ? (
                  <label className="form-label">
                    Types and presets (YAML)
                    <textarea
                      className="form-control editor"
                      rows={24}
                      spellCheck={false}
                      value={source}
                      onChange={(e) => edit(e.target.value)}
                    />
                  </label>
                ) : mode === "usage" ? (
                  <div className="stack">
                    <p>
                      Existing publications retain their stored types and values. Create a new
                      publication revision to apply changes.
                    </p>
                    {usages.isPending ? (
                      <Loading what="publication references" />
                    ) : usages.isError ? (
                      <Failure error={usages.error} />
                    ) : (
                      <ul>
                        {(usages.data ?? [])
                          .filter((item) =>
                            (section === "definitions" ? item.types : item.presets).includes(
                              key,
                            ),
                          )
                          .map((item) => (
                            <li key={item.slug}>
                              <Link href={`/catalog/${item.slug}`}>{item.title}</Link>
                            </li>
                          ))}
                      </ul>
                    )}
                  </div>
                ) : parsed.error ? (
                  <StatusReport tone="error" title="Correct the YAML before visual editing">
                    {parsed.error}
                  </StatusReport>
                ) : key ? (
                  <>
                    <label className="form-label">
                      Identifier
                      <input
                        key={`${section}-${key}`}
                        className="form-control"
                        defaultValue={key}
                        disabled={Object.hasOwn(storedEntries, key)}
                        onBlur={(e) => {
                          const next = e.target.value.trim();
                          if (next === key) return;
                          if (
                            !/^[A-Za-z_][A-Za-z0-9_-]{0,127}$/.test(next) ||
                            Object.hasOwn(entries, next)
                          ) {
                            setLocalError(
                              "Use a unique identifier containing letters, numbers, underscores, or hyphens.",
                            );
                            e.target.value = key;
                            return;
                          }
                          edit((current) => renameLibraryKey(current, [section, key], next));
                          select(next);
                        }}
                      />
                    </label>
                    {section === "definitions" ? (
                      <TypeDefinitionEditor
                        key={key}
                        typeKey={key}
                        definition={entry}
                        definitions={definitions}
                        set={(path, value) => change([section, key, ...path], value)}
                        remove={(path) => remove([section, key, ...path])}
                        move={(field, offset) =>
                          edit((current) => moveField(current, key, field, offset))
                        }
                        rename={(field, name) =>
                          edit((current) =>
                            renameLibraryKey(current, [section, key, "fields", field], name),
                          )
                        }
                      />
                    ) : (
                      <div className="stack">
                        <label className="form-label">
                          Preset display name
                          <input
                            className="form-control"
                            value={String(entry.label || "")}
                            onChange={(e) => change([section, key, "label"], e.target.value)}
                          />
                        </label>
                        <label className="form-label">
                          Preset description
                          <input
                            className="form-control"
                            value={String(entry.description || "")}
                            onChange={(e) =>
                              change([section, key, "description"], e.target.value)
                            }
                          />
                        </label>
                        <label className="form-label">
                          Preset type
                          <select
                            className="form-select"
                            value={String(entry.type_ref || "")}
                            onChange={(e) => change([section, key, "type_ref"], e.target.value)}
                          >
                            <option value="">Choose a type</option>
                            {Object.keys(definitions).map((name) => (
                              <option key={name}>{name}</option>
                            ))}
                          </select>
                        </label>
                        <label className="form-label">
                          Preset shape
                          <select
                            className="form-select"
                            value={String(entry.container || "single")}
                            onChange={(e) =>
                              change([section, key, "container"], e.target.value)
                            }
                          >
                            <option value="single">Single</option>
                            <option value="list">List</option>
                            <option value="map">Named map</option>
                          </select>
                        </label>
                        {schema ? (
                          <TypedField
                            key={`${key}-${String(entry.type_ref)}-${String(entry.container)}`}
                            id="preset-value"
                            schema={{
                              ...schema,
                              container: String(entry.container || "single"),
                            }}
                            value={entry.value}
                            onChange={(value) => change([section, key, "value"], value)}
                          />
                        ) : null}
                      </div>
                    )}
                    {section === "definitions" ? (
                      <details open className="library-preview">
                        <summary>Form preview</summary>
                        <div className="stack">
                          <label className="form-label">
                            Preview shape
                            <select
                              className="form-select"
                              value={shape}
                              onChange={(e) => {
                                setShape(e.target.value);
                                setPreview(undefined);
                              }}
                            >
                              <option value="single">Single</option>
                              <option value="list">List</option>
                              <option value="map">Named map</option>
                            </select>
                          </label>
                          {schema ? (
                            <TypedField
                              key={`${section}-${key}-${shape}`}
                              id="library-preview"
                              formId="library-preview-values"
                              schema={{ ...schema, container: shape }}
                              value={preview}
                              onChange={setPreview}
                            />
                          ) : (
                            <p className="field__error">{previewError}</p>
                          )}
                        </div>
                      </details>
                    ) : null}
                    <details>
                      <summary>Remove from the library</summary>
                      <p>
                        Existing publications keep their snapshots. Other types and presets that
                        reference this entry must be updated before the library can be saved.
                      </p>
                      <button
                        type="button"
                        className="btn btn-outline-danger"
                        onClick={() => setConfirmation("remove")}
                      >
                        Remove {key}
                      </button>
                    </details>
                  </>
                ) : null}
                {parsed.error && mode === "yaml" ? (
                  <StatusReport tone="error" title="Invalid YAML">
                    {parsed.error}
                  </StatusReport>
                ) : null}
                <div className="button-row">
                  <button
                    type="button"
                    className="btn"
                    disabled={busy || !!parsed.error}
                    aria-busy={validate.isPending}
                    onClick={() => validate.mutate(source)}
                  >
                    Validate
                  </button>
                  <button
                    type="submit"
                    className="btn btn-primary"
                    disabled={busy || !!parsed.error}
                    aria-busy={save.isPending}
                  >
                    {save.isPending ? "Saving…" : "Save library"}
                  </button>
                  <span className="muted">{editing ? "Unsaved draft" : "Saved library"}</span>
                </div>
                {validate.data?.source_text === source ? (
                  <StatusReport tone="success" title="Library is valid">
                    {Object.keys(validate.data.schemas).length} types and{" "}
                    {Object.keys(validate.data.presets).length} presets.
                  </StatusReport>
                ) : null}
                {save.isSuccess ? (
                  <StatusReport tone="success" title="Publication library saved" />
                ) : null}
                {importer.isSuccess ? (
                  <StatusReport
                    tone="success"
                    title="Import loaded into draft. Review and save it."
                  >
                    <ul>
                      {importer.data.notes.map((note, index) => (
                        <li key={index}>{note}</li>
                      ))}
                    </ul>
                  </StatusReport>
                ) : null}
                {localError ? (
                  <StatusReport tone="error" title="Check the draft">
                    {localError}
                  </StatusReport>
                ) : null}
                {[validate, save, importer].map((mutation, index) =>
                  mutation.isError ? <Failure key={index} error={mutation.error} /> : null,
                )}
                {save.isError ? (
                  <button
                    type="button"
                    className="btn"
                    onClick={() => setConfirmation("reload")}
                  >
                    Discard edits and reload
                  </button>
                ) : null}
              </section>
            </div>
          </fieldset>
        </form>
      ) : null}
      <Dialog
        open={confirmation !== null}
        title={
          confirmation === "remove"
            ? `Remove ${key}?`
            : confirmation === "example"
              ? "Load the example?"
              : "Discard the draft?"
        }
        onClose={() => setConfirmation(null)}
      >
        <p>
          {confirmation === "remove"
            ? "This removes the entry from the draft. Existing publications retain their snapshots. Review dependent types and presets before saving."
            : confirmation === "example"
              ? "The example replaces the current draft. The saved library changes only when you click Save library."
              : "Unsaved edits will be discarded and the current saved library loaded."}
        </p>
        <button
          type="button"
          className={`btn ${confirmation === "remove" ? "btn-danger" : "btn-primary"}`}
          onClick={() => {
            if (confirmation === "remove") {
              remove([section, key]);
              select("");
            }
            if (confirmation === "example") {
              edit(LIBRARY_EXAMPLE);
              select("");
            }
            if (confirmation === "reload") {
              setEditing(null);
              save.reset();
              validate.reset();
              void library.refetch();
            }
            setConfirmation(null);
          }}
        >
          Confirm{" "}
          {confirmation === "remove"
            ? "removal"
            : confirmation === "example"
              ? "example draft"
              : "discard"}
        </button>
      </Dialog>
    </div>
  );
}
