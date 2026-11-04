"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useApi } from "@/features/auth/session";
import { Dialog } from "@/components/ui/Dialog";
import { Empty, Failure, Loading, StatusReport } from "@/components/ui/states";
import { savedValues, type SavedValue } from "@/lib/api";
import { ValueEditor } from "./ValueEditor";
import { initialTypedValue, type TypeSchema } from "./TypedField";

interface Context {
  entry: string;
  field_key: string;
  label: string;
  type_schema: TypeSchema;
}
const QUERY = ["saved-values"];

export function SavedValuesScreen() {
  const client = useApi();
  const queries = useQueryClient();
  const list = useQuery({
    queryKey: [...QUERY, "all"],
    queryFn: () => savedValues.list(client),
  });
  const contexts = useQuery({
    queryKey: [...QUERY, "contexts"],
    queryFn: () => client.get<Context[]>("/saved-values/contexts"),
  });
  const [selection, select] = useState("");
  const [search, setSearch] = useState("");
  const [creating, setCreating] = useState(false);
  const items = list.data?.items ?? [];
  const item = items.find((value) => value.id === selection) ?? items[0];
  if (!selection && item && !list.isFetching) select(item.id);
  const groupKey = (value: SavedValue) => `${value.type_key}:${value.container}`;
  const groups = new Map<string, SavedValue[]>();
  items.forEach((value) =>
    groups.set(groupKey(value), [...(groups.get(groupKey(value)) ?? []), value]),
  );
  const refresh = () => void queries.invalidateQueries({ queryKey: QUERY });
  return (
    <div className="stack">
      <header className="page-header">
        <div>
          <h1>My saved values</h1>
          <p className="muted">
            Private named configurations, reusable in compatible published forms.
          </p>
        </div>
        <button type="button" className="btn btn-primary" onClick={() => setCreating(true)}>
          New saved value
        </button>
      </header>
      {list.isPending ? (
        <Loading what="saved values" />
      ) : list.isError ? (
        <Failure error={list.error} />
      ) : items.length === 0 ? (
        <Empty
          title="No personal values saved yet."
          detail="Create one here or save a completed value in a catalog form."
        />
      ) : (
        <div className="library-workspace">
          <aside className="library-list stack stack--compact">
            <label className="form-label">
              Find saved values
              <input
                className="form-control"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </label>
            {[...groups.entries()]
              .filter(([, values]) =>
                values.some((value) =>
                  `${value.name} ${value.type_key} ${value.type_schema?.label || ""}`
                    .toLowerCase()
                    .includes(search.toLowerCase()),
                ),
              )
              .map(([key, values]) => (
                <button
                  type="button"
                  className={`btn library-list__entry ${item && groupKey(item) === key ? "btn-primary" : "btn-outline-secondary"}`}
                  key={key}
                  onClick={() => select(values[0]!.id)}
                >
                  <span>{String(values[0]!.type_schema?.label || values[0]!.type_key)}</span>
                  <small>
                    {values[0]!.container} · {values.length} saved
                  </small>
                </button>
              ))}
          </aside>
          {item ? (
            <section className="panel card card-body stack">
              <label className="form-label">
                Named saved value
                <select
                  className="form-select"
                  value={item.id}
                  onChange={(e) => select(e.target.value)}
                >
                  {(groups.get(groupKey(item)) ?? []).map((value) => (
                    <option key={value.id} value={value.id}>
                      {value.name}
                      {value.is_default ? " · My default" : ""}
                    </option>
                  ))}
                </select>
              </label>
              <SavedValueEditor
                key={item.id}
                item={item}
                contexts={contexts.data ?? []}
                onChange={refresh}
                onSelect={select}
              />
            </section>
          ) : null}
        </div>
      )}
      <Dialog
        open={creating}
        title="New personal saved value"
        onClose={() => setCreating(false)}
      >
        {contexts.isPending ? (
          <Loading what="available fields" />
        ) : contexts.isError ? (
          <Failure error={contexts.error} />
        ) : (
          <CreateSavedValue
            contexts={contexts.data ?? []}
            onCreated={(value) => {
              refresh();
              select(value.id);
              setCreating(false);
            }}
          />
        )}
      </Dialog>
    </div>
  );
}

function SavedValueEditor({
  item,
  contexts,
  onChange,
  onSelect,
}: {
  item: SavedValue;
  contexts: Context[];
  onChange: () => void;
  onSelect: (id: string) => void;
}) {
  const client = useApi();
  const [name, setName] = useState(item.name);
  const [value, setValue] = useState(item.value);
  const [deleting, setDeleting] = useState(false);
  const [copying, setCopying] = useState(false);
  const [adapting, setAdapting] = useState(false);
  const [copyName, setCopyName] = useState(`${item.name} copy`);
  const update = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      client.patch<SavedValue>(`/saved-values/${item.id}`, { body }),
    onSuccess: onChange,
  });
  const duplicate = useMutation({
    mutationFn: () =>
      client.post<SavedValue>(`/saved-values/${item.id}/duplicate`, {
        body: { name: copyName },
      }),
    onSuccess: (next) => {
      onChange();
      onSelect(next.id);
      setCopying(false);
    },
  });
  const remove = useMutation({
    mutationFn: () => savedValues.remove(client, item.id),
    onSuccess: () => {
      onSelect("");
      onChange();
      setDeleting(false);
    },
  });
  return (
    <>
      <form
        className="stack"
        onSubmit={(e) => {
          e.preventDefault();
          update.mutate({ name, value, replace_value: true });
        }}
      >
        <fieldset className="stack" disabled={update.isPending}>
          <div className="page-header">
            <h2>{item.name}</h2>
            {item.is_default ? <span className="badge bg-green-lt">My default</span> : null}
          </div>
          <label className="form-label">
            Name
            <input
              className="form-control"
              required
              maxLength={256}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <div className="button-row">
            <button
              type="button"
              className="btn"
              disabled={update.isPending}
              onClick={() => update.mutate({ is_default: !item.is_default })}
            >
              {item.is_default ? "Remove my default" : "Set as my default"}
            </button>
            <button type="button" className="btn" onClick={() => setCopying(true)}>
              Duplicate
            </button>
            <button
              type="button"
              className="btn btn-outline-danger"
              onClick={() => setDeleting(true)}
            >
              Delete
            </button>
          </div>
          <ValueEditor
            id="personal-value"
            schema={item.type_schema as TypeSchema}
            value={value}
            onChange={setValue}
          />
          <p className="muted">
            Edits use this value’s saved type snapshot. Each published form checks compatibility
            before offering it.
          </p>
          <button
            type="submit"
            className="btn btn-primary align-start"
            disabled={update.isPending}
            aria-busy={update.isPending}
          >
            {update.isPending ? "Saving…" : "Save value"}
          </button>
          {update.isSuccess ? (
            <StatusReport tone="success" title="Saved value updated" />
          ) : null}
          {update.isError ? <Failure error={update.error} /> : null}
        </fieldset>
      </form>
      <button
        type="button"
        className="btn btn-outline-primary align-start"
        disabled={!contexts.length}
        onClick={() => setAdapting(true)}
      >
        Copy to another published field
      </button>
      <Dialog
        open={adapting}
        title="Copy and adapt saved value"
        onClose={() => setAdapting(false)}
      >
        <p>
          The original keeps its saved schema and value. Choose a current published field and
          review the copied values.
        </p>
        <CreateSavedValue
          contexts={contexts}
          initialName={`${item.name} adapted`}
          initialValue={item.value}
          onCreated={(next) => {
            onChange();
            onSelect(next.id);
            setAdapting(false);
          }}
        />
      </Dialog>
      <Dialog open={copying} title="Duplicate saved value" onClose={() => setCopying(false)}>
        <label className="form-label">
          New name
          <input
            className="form-control"
            value={copyName}
            onChange={(e) => setCopyName(e.target.value)}
          />
        </label>
        <button
          className="btn btn-primary"
          disabled={!copyName.trim() || duplicate.isPending}
          onClick={() => duplicate.mutate()}
        >
          Create copy
        </button>
        {duplicate.isError ? <Failure error={duplicate.error} /> : null}
      </Dialog>
      <Dialog open={deleting} title={`Delete ${item.name}?`} onClose={() => setDeleting(false)}>
        <p>This removes the personal saved value. Existing runs keep their recorded inputs.</p>
        <button
          className="btn btn-danger"
          disabled={remove.isPending}
          onClick={() => remove.mutate()}
        >
          Delete saved value
        </button>
        {remove.isError ? <Failure error={remove.error} /> : null}
      </Dialog>
    </>
  );
}

function CreateSavedValue({
  contexts,
  onCreated,
  initialValue,
  initialName = "",
}: {
  contexts: Context[];
  onCreated: (value: SavedValue) => void;
  initialValue?: unknown;
  initialName?: string;
}) {
  const client = useApi();
  const [selected, setSelected] = useState(0);
  const [name, setName] = useState(initialName);
  const [value, setValue] = useState<unknown>(initialValue);
  const context = contexts[selected];
  const save = useMutation({
    mutationFn: () =>
      savedValues.save(client, context!.entry, {
        fieldKey: context!.field_key,
        name,
        value: value === undefined ? initialTypedValue(context!.type_schema) : value,
      }),
    onSuccess: onCreated,
  });
  return context ? (
    <form
      className="stack"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <label className="form-label">
        Published field
        <select
          className="form-select"
          value={selected}
          onChange={(e) => {
            setSelected(Number(e.target.value));
            setValue(initialValue);
          }}
        >
          {contexts.map((entry, index) => (
            <option key={`${entry.entry}:${entry.field_key}`} value={index}>
              {entry.label}
            </option>
          ))}
        </select>
      </label>
      <label className="form-label">
        Name
        <input
          className="form-control"
          required
          maxLength={256}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </label>
      <ValueEditor
        key={selected}
        id="new-personal-value"
        schema={context.type_schema}
        value={value}
        onChange={setValue}
      />
      <button
        type="submit"
        className="btn btn-primary"
        disabled={save.isPending}
        aria-busy={save.isPending}
      >
        Save personal value
      </button>
      {save.isError ? <Failure error={save.error} /> : null}
    </form>
  ) : (
    <p>
      No published field currently permits saving. Open a publication that allows personal saved
      values first.
    </p>
  );
}
