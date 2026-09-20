"use client";

/**
 * What a task can import.
 *
 * In a generic Python executor "what can I call?" *is* the authoring
 * experience: an author writing `package: labUtils.demo, method: run` is
 * guessing unless something can tell them what exists. This is that something
 * — and the place an admin installs it in the first place.
 *
 * Three things the screen has to be honest about.
 *
 * **An install takes minutes and the request waits.** A wheel that compiles
 * is not fast, and pretending otherwise with a spinner that resolves in a
 * second would be a lie. The button says what is happening and the history
 * below records it either way.
 *
 * **Installing does not disturb anything running.** It builds the next
 * generation and moves a pointer (ADR 0028). Saying so where the button is
 * removes the question an admin would otherwise have to ask somebody.
 *
 * **An editable install cannot be reproduced.** It is a link to a working
 * tree, so the source behind it can change with nobody's knowledge. Every run
 * using it is marked, and so is the environment.
 */

import { useState } from "react";

import { DataTable, type Column } from "@/components/ui/DataTable";
import { Dialog } from "@/components/ui/Dialog";
import { Field } from "@/components/ui/Field";
import { Empty, Failure, Loading } from "@/components/ui/states";
import {
  useCallables,
  useChangePackages,
  useCreateEnvironment,
  useEnvironment,
  useEnvironmentAction,
  useEnvironmentOperations,
  useEnvironments,
  useGenerations,
} from "@/features/environments/useEnvironments";
import type { GenerationSummary, InstalledPackage, PackageOperation } from "@/lib/api";
import { formatTimestamp } from "@/lib/format";
import { fieldErrors } from "@/lib/form";

const PACKAGES: Column<InstalledPackage>[] = [
  { key: "name", header: "Package", render: (row) => <code>{row.name}</code> },
  { key: "version", header: "Version", render: (row) => row.version },
  {
    key: "editable",
    header: "",
    render: (row) =>
      row.editable_path ? (
        <span className="badge badge--warn" title={row.editable_path}>
          from a working tree
        </span>
      ) : null,
  },
];

const GENERATIONS: Column<GenerationSummary>[] = [
  {
    key: "digest",
    header: "Generation",
    // The content hash, short. Two installs arriving at the same package set
    // are the same generation, and this is where that shows.
    render: (row) => <code>{row.digest.replace("sha256:", "").slice(0, 12)}</code>,
  },
  { key: "packages", header: "Packages", render: (row) => row.package_count },
  {
    key: "built",
    header: "Built",
    render: (row) => (row.built_at ? formatTimestamp(row.built_at) : "—"),
  },
  {
    key: "state",
    header: "",
    render: (row) =>
      row.current ? (
        <span className="badge badge--good">what new runs pin</span>
      ) : row.reclaimed_at ? (
        // The directory is gone; the row is not. It still answers what the
        // runs that pinned it imported.
        <span className="badge" title={`Reclaimed ${formatTimestamp(row.reclaimed_at)}`}>
          reclaimed
        </span>
      ) : null,
  },
];

const OPERATIONS: Column<PackageOperation>[] = [
  {
    key: "status",
    header: "",
    render: (row) => (
      <span className={`badge badge--${row.status === "succeeded" ? "good" : "bad"}`}>
        {row.status}
      </span>
    ),
  },
  { key: "operation", header: "What", render: (row) => row.operation },
  { key: "specifier", header: "Package", render: (row) => <code>{row.specifier}</code> },
  { key: "when", header: "When", render: (row) => formatTimestamp(row.created_at) },
];

function Packages({ environmentId }: { environmentId: string }) {
  const detail = useEnvironment(environmentId);
  const change = useChangePackages(environmentId);
  const action = useEnvironmentAction(environmentId);
  const operations = useEnvironmentOperations(environmentId);
  const generations = useGenerations(environmentId);
  const [specifier, setSpecifier] = useState("");
  const [module, setModule] = useState("");
  const callables = useCallables(environmentId, module);

  if (detail.isPending) return <Loading what="this environment" />;
  if (detail.isError)
    return <Failure error={detail.error} onRetry={() => void detail.refetch()} />;

  const problems = fieldErrors(change.error);
  const packages = detail.data.packages ?? [];

  return (
    <div className="stack">
      {detail.data.reproducibility_note ? (
        <p className="field__error" role="alert">
          {detail.data.reproducibility_note}
        </p>
      ) : null}

      {detail.data.locked_reason ? (
        <div className="stack stack--tight">
          <p className="muted">Busy: {detail.data.locked_reason}.</p>
          {/* A build that died leaves a lock nobody can clear, and every
              later install is refused by something that is not running. */}
          <button type="button" className="button" onClick={() => action.mutate("unlock")}>
            Clear the lock
          </button>
        </div>
      ) : (
        <form
          className="button-row"
          onSubmit={(event) => {
            event.preventDefault();
            if (specifier.trim())
              change.mutate({ operation: "install", specifier: specifier.trim() });
          }}
        >
          <Field id="specifier" label="Install a package" error={problems.for("specifier")}>
            {(props) => (
              <input
                {...props}
                type="text"
                placeholder="pandas==2.2.1"
                spellCheck={false}
                value={specifier}
                onChange={(event) => setSpecifier(event.target.value)}
              />
            )}
          </Field>
          <button type="submit" className="button button--primary" disabled={change.isPending}>
            {change.isPending ? "Building…" : "Install"}
          </button>
          {specifier.trim() ? (
            <button
              type="button"
              className="button"
              disabled={change.isPending}
              onClick={() =>
                change.mutate({ operation: "uninstall", specifier: specifier.trim() })
              }
            >
              Uninstall
            </button>
          ) : null}
        </form>
      )}

      <p className="muted">
        An install builds the next generation of this environment and moves a pointer to it.
        Anything already running keeps the generation it started with, so nothing in flight is
        disturbed. It can take several minutes when a package has to be compiled.
      </p>

      {change.isError ? <Failure error={change.error} /> : null}
      {change.data && change.data.status === "failed" ? (
        <pre className="log" aria-label="Install output">
          {change.data.log}
        </pre>
      ) : null}

      <section className="stack stack--tight">
        <h3>Installed</h3>
        {packages.length === 0 ? (
          <Empty title="Nothing is installed yet." />
        ) : (
          <DataTable
            rows={packages}
            columns={PACKAGES}
            caption="Installed packages"
            rowKey={(row) => row.name}
          />
        )}
      </section>

      <section className="stack stack--tight">
        <h3>Generations</h3>
        <p className="muted">
          Every build of this environment. A run pins one and keeps it, so they outlive the
          install that replaced them. The janitor removes the directory of one no run can still
          reach; the record of what it contained stays.
        </p>
        {generations.data?.items.length ? (
          <DataTable
            rows={generations.data.items}
            columns={GENERATIONS}
            caption="Environment generations"
            rowKey={(row) => row.id}
          />
        ) : (
          <Empty title="Nothing has been built yet." />
        )}
      </section>

      <section className="stack stack--tight">
        <h3>What a pipeline can call</h3>
        <Field id="module" label="Module" hint="Leave blank to list what is importable.">
          {(props) => (
            <input
              {...props}
              type="text"
              placeholder="labUtils.demo"
              spellCheck={false}
              value={module}
              onChange={(event) => setModule(event.target.value)}
            />
          )}
        </Field>
        {callables.isError ? <Failure error={callables.error} /> : null}
        {callables.data?.callables?.length ? (
          <ul className="value-list">
            {callables.data.callables.map((item) => (
              <li key={item.name}>
                <code>
                  {item.name}
                  {item.signature}
                </code>
                {item.summary ? <span className="muted"> — {item.summary}</span> : null}
              </li>
            ))}
          </ul>
        ) : callables.data?.modules?.length ? (
          <p className="muted">{callables.data.modules.join(", ")}</p>
        ) : null}
      </section>

      <section className="stack stack--tight">
        <h3>History</h3>
        <p className="muted">
          Why a pipeline that worked last month fails today. Failed installs are here too.
        </p>
        {operations.data?.items.length ? (
          <DataTable
            rows={operations.data.items}
            columns={OPERATIONS}
            caption="Install history"
            rowKey={(row) => row.id}
          />
        ) : (
          <Empty title="Nothing has been installed yet." />
        )}
      </section>
    </div>
  );
}

export function EnvironmentsScreen() {
  const query = useEnvironments();
  const create = useCreateEnvironment();
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [chosen, setChosen] = useState<string | null>(null);

  if (query.isPending) return <Loading what="environments" />;
  if (query.isError)
    return <Failure error={query.error} onRetry={() => void query.refetch()} />;

  const items = query.data.items;
  const selected = chosen ?? items.find((item) => item.is_default)?.id ?? items[0]?.id ?? null;

  return (
    <div className="stack">
      <header className="page-header">
        <div>
          <h1>Environments</h1>
          <p className="muted">
            What a task can import. A run records the exact set it used, so a result can be
            traced back to the libraries that produced it.
          </p>
        </div>
        <button
          type="button"
          className="button button--primary"
          onClick={() => setCreating(true)}
        >
          New environment
        </button>
      </header>

      {items.length === 0 ? (
        <Empty
          title="No environment yet."
          detail="Tasks run against the image alone — the runner and the standard library."
        />
      ) : (
        <>
          <div className="button-row">
            {items.map((item) => (
              <button
                key={item.id}
                type="button"
                className={item.id === selected ? "button button--primary" : "button"}
                aria-pressed={item.id === selected}
                onClick={() => setChosen(item.id)}
              >
                {item.name}
                {item.is_default ? " (default)" : ""}
              </button>
            ))}
          </div>
          {selected ? <Packages environmentId={selected} /> : null}
        </>
      )}

      <Dialog open={creating} title="New environment" onClose={() => setCreating(false)}>
        <p className="muted">
          It starts empty. What belongs in a lab&apos;s environment is the lab&apos;s decision.
        </p>
        <Field id="env-name" label="Name" error={fieldErrors(create.error).for("name")}>
          {(props) => (
            <input
              {...props}
              type="text"
              value={name}
              placeholder="lab"
              onChange={(event) => setName(event.target.value)}
            />
          )}
        </Field>
        {create.isError ? <Failure error={create.error} /> : null}
        <div className="dialog__actions">
          <button
            type="button"
            className="button button--quiet"
            onClick={() => setCreating(false)}
          >
            Cancel
          </button>
          <button
            type="button"
            className="button button--primary"
            disabled={!name.trim() || create.isPending}
            onClick={() =>
              create.mutate(
                { name: name.trim(), makeDefault: items.length === 0 },
                {
                  onSuccess: (made) => {
                    setCreating(false);
                    setName("");
                    setChosen(made.id);
                  },
                },
              )
            }
          >
            {create.isPending ? "Building…" : "Create"}
          </button>
        </div>
      </Dialog>
    </div>
  );
}
