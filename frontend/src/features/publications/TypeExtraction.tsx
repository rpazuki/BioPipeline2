"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useApi } from "@/features/auth/session";
import { environments } from "@/lib/api";
import { Failure } from "@/components/ui/states";
import { libraryDocument, mapping, mergeLibrarySource } from "./library-document";

export function TypeExtraction({
  source,
  onMerge,
}: {
  source: string;
  onMerge: (source: string) => void;
}) {
  const client = useApi();
  const [open, setOpen] = useState(false),
    [environment, setEnvironment] = useState(""),
    [classPath, setClassPath] = useState("");
  const [error, setError] = useState("");
  const list = useQuery({
    queryKey: ["environments"],
    queryFn: () => environments.list(client),
    enabled: open,
  });
  const extract = useMutation({
    mutationFn: () =>
      client.get<{ source_text: string; root: string; notes: string[] }>(
        `/environments/${environment}/types`,
        { query: { class_path: classPath } },
      ),
  });
  return (
    <details onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary>Extract from a Python class</summary>
      <div className="stack">
        <label className="form-label">
          Execution environment
          <select
            className="form-select"
            value={environment}
            onChange={(e) => {
              setEnvironment(e.target.value);
              extract.reset();
            }}
          >
            <option value="">Choose an environment</option>
            {list.data?.items.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        </label>
        <label className="form-label">
          Fully qualified class name
          <input
            className="form-control"
            maxLength={512}
            placeholder="package.module.Options"
            value={classPath}
            onChange={(e) => {
              setClassPath(e.target.value);
              extract.reset();
            }}
          />
        </label>
        <button
          type="button"
          className="btn"
          disabled={!environment || !classPath.trim() || extract.isPending}
          aria-busy={extract.isPending}
          onClick={() => extract.mutate()}
        >
          {extract.isPending ? "Inspecting…" : "Preview extracted type"}
        </button>
        {list.isError ? <Failure error={list.error} /> : null}
        {extract.isError ? <Failure error={extract.error} /> : null}
        {extract.data ? (
          <>
            <pre>{extract.data.source_text}</pre>
            <ul>
              {extract.data.notes.map((note, index) => (
                <li key={index}>{note}</li>
              ))}
            </ul>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => {
                try {
                  const current = mapping(libraryDocument(source).toJS()).definitions;
                  const names = Object.keys(
                    mapping(
                      mapping(libraryDocument(extract.data.source_text).toJS()).definitions,
                    ),
                  );
                  if (names.some((name) => Object.hasOwn(mapping(current), name)))
                    throw new Error(
                      "An extracted type name already exists. Rename it in YAML before merging.",
                    );
                  onMerge(mergeLibrarySource(source, extract.data.source_text));
                  setError("");
                } catch (err) {
                  setError(String(err));
                }
              }}
            >
              Add reviewed definitions to draft
            </button>
          </>
        ) : null}
        {error ? (
          <p role="alert" className="field__error">
            {error}
          </p>
        ) : null}
      </div>
    </details>
  );
}
