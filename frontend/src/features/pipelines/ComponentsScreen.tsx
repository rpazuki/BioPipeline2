"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { Dialog } from "@/components/ui/Dialog";
import { Empty, Failure, Loading, StatusReport } from "@/components/ui/states";
import { useApi } from "@/features/auth/session";
import { componentLibraries, type ComponentSource } from "@/lib/api";

const STARTER = `graphs:
  convert_value:
    - name: converted
      package: builtins
      method: str
      parameters:
        object: example
`;

export function ComponentsScreen() {
  const client = useApi();
  const [editing, setEditing] = useState<string | null>(null);
  const list = useQuery({
    queryKey: ["component-libraries"],
    queryFn: () => componentLibraries.list(client),
  });
  const source = useQuery({
    queryKey: ["component-source", editing],
    queryFn: () => componentLibraries.source(client, editing as string),
    enabled: editing !== null && editing !== "",
  });
  return (
    <section className="stack">
      <header className="page-header">
        <div>
          <h2>Components</h2>
          <p>
            Reusable groups of Python calls. Pipelines select a named graph from a component
            library.
          </p>
        </div>
        <button className="button button--primary" onClick={() => setEditing("")}>
          New component
        </button>
      </header>
      {list.isPending ? <Loading what="components" /> : null}
      {list.isError ? <Failure error={list.error} onRetry={() => void list.refetch()} /> : null}
      {list.data?.length === 0 ? (
        <Empty
          title="No components yet."
          detail="Create a component, then use it in a pipeline."
        />
      ) : null}
      {list.data?.length ? (
        <table>
          <caption>Component libraries</caption>
          <thead>
            <tr>
              <th>Library</th>
              <th>Graphs</th>
              <th>Status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {list.data.map((item) => (
              <tr key={item.name}>
                <td>
                  <code>{item.name}</code>
                </td>
                <td>{item.graphs.join(", ") || "—"}</td>
                <td>{item.error ? "Needs correction" : "Valid"}</td>
                <td>
                  <button className="button" onClick={() => setEditing(item.name)}>
                    View / edit {item.name}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      <Dialog
        open={editing !== null}
        title={editing ? `Component: ${editing}` : "New component"}
        onClose={() => setEditing(null)}
      >
        {editing === "" ? <ComponentEditor key="new" onClose={() => setEditing(null)} /> : null}
        {editing ? (
          <>
            {source.isPending ? <Loading what="component source" /> : null}
            {source.isError ? (
              <Failure error={source.error} onRetry={() => void source.refetch()} />
            ) : null}
            {source.data ? (
              <ComponentEditor
                key={editing}
                initial={source.data}
                onClose={() => setEditing(null)}
              />
            ) : null}
          </>
        ) : null}
      </Dialog>
    </section>
  );
}

function ComponentEditor({
  initial,
  onClose,
}: {
  initial?: ComponentSource;
  onClose: () => void;
}) {
  const client = useApi();
  const cache = useQueryClient();
  const [name, setName] = useState(initial?.name ?? "my_component.yaml");
  const [source, setSource] = useState(initial?.source_text ?? STARTER);
  const [expected, setExpected] = useState(initial?.digest ?? null);
  const [saved, setSaved] = useState<ComponentSource | null>(initial ?? null);
  const validation = useMutation({
    mutationFn: (text: string) => componentLibraries.validate(client, text),
  });
  const versions = useQuery({
    queryKey: ["component-revisions", name],
    queryFn: () => componentLibraries.revisions(client, name),
    enabled: expected !== null,
  });
  const save = useMutation({
    mutationFn: () => componentLibraries.save(client, name, source, expected),
    onSuccess: (result) => {
      setExpected(result.digest);
      setSaved(result);
      void cache.invalidateQueries({ queryKey: ["component-libraries"] });
      void cache.invalidateQueries({ queryKey: ["component-source", name] });
      void cache.invalidateQueries({ queryKey: ["component-revisions", name] });
    },
  });
  const validated = validation.data?.ok === true && validation.variables === source;
  return (
    <div className="stack">
      <label htmlFor="component-name">Library filename</label>
      <input
        id="component-name"
        disabled={save.isPending}
        value={name}
        readOnly={expected !== null}
        onChange={(event) => setName(event.target.value)}
      />
      <label htmlFor="component-source">Component document</label>
      <textarea
        id="component-source"
        disabled={save.isPending}
        className="editor"
        rows={20}
        spellCheck={false}
        value={source}
        onChange={(event) => {
          setSource(event.target.value);
          save.reset();
        }}
      />
      <p className="muted">
        Validate the component structure before saving. Compile its pipeline to check how inputs
        and parameters are connected.
      </p>
      <p className="muted">
        Legacy component documents can use a pipelines / Processes layout. Convert their Inputs
        preparation and Outputs saving rules into explicit calls and pipeline outputs.
      </p>
      <div className="button-row">
        <button
          aria-busy={validation.isPending}
          data-state={
            validation.variables === source
              ? validation.isError || validation.data?.ok === false
                ? "error"
                : validation.data?.ok
                  ? "success"
                  : undefined
              : undefined
          }
          className="button"
          disabled={validation.isPending || save.isPending}
          onClick={() => validation.mutate(source)}
        >
          {validation.isPending ? "Validating…" : "Validate component"}
        </button>
        <button
          aria-busy={save.isPending}
          data-state={save.isError ? "error" : save.isSuccess ? "success" : undefined}
          className="button button--primary"
          disabled={!validated || !name || save.isPending}
          onClick={() => save.mutate()}
        >
          {save.isPending ? "Saving…" : "Save component revision"}
        </button>
        <button className="button" onClick={onClose}>
          Close
        </button>
      </div>
      {validation.isError && validation.variables === source ? (
        <Failure error={validation.error} />
      ) : null}
      {validation.data && validation.variables === source ? (
        <StatusReport
          tone={validation.data.ok ? "success" : "error"}
          title={
            validation.data.ok
              ? `Valid graphs: ${(validation.data.graphs ?? []).join(", ")}`
              : (validation.data.message ?? "Component validation failed.")
          }
        />
      ) : null}
      {save.isError ? <Failure error={save.error} /> : null}
      {save.isSuccess ? (
        <StatusReport tone="success" title="Component revision saved." />
      ) : null}
      {saved && source === saved.source_text && !saved.error ? (
        <section>
          <h3>Use in a pipeline</h3>
          <p>
            Choose a graph to start a new pipeline. Configure its inputs and parameters before
            running it.
          </p>
          {saved.graphs.map((graph) => (
            <p key={graph}>
              <Link
                className="button"
                href={`/pipelines/new?library=${encodeURIComponent(saved.reference)}&graph=${encodeURIComponent(graph)}`}
              >
                Use {graph} in a pipeline
              </Link>
            </p>
          ))}
          <pre>{`components:\n  selected_component:\n    library: ${JSON.stringify(saved.reference)}\n    graph: ${JSON.stringify(saved.graphs[0])}\nstages:\n  - name: process\n    uses: selected_component`}</pre>
        </section>
      ) : null}
      {expected !== null ? (
        <details>
          <summary>Saved component revisions</summary>
          {versions.isError ? <Failure error={versions.error} /> : null}
          {versions.data?.map((version) => (
            <p key={version.digest}>
              <code>{version.digest.slice(0, 12)}</code>{" "}
              <button
                className="button"
                onClick={() => {
                  setSource(version.source_text);
                  validation.reset();
                  save.reset();
                  setSaved(version);
                }}
              >
                Load source {version.digest.slice(0, 12)}
              </button>
            </p>
          ))}
        </details>
      ) : null}
    </div>
  );
}
