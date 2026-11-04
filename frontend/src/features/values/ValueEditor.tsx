"use client";

import { useRef, useState } from "react";
import { parseDocument, stringify } from "yaml";
import { TypedField, type TypeSchema } from "./TypedField";

/** Edit structured values visually or as YAML while retaining invalid source for correction. */
export function ValueEditor({
  id,
  schema,
  value,
  onChange,
}: {
  id: string;
  schema: TypeSchema;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const [mode, setMode] = useState("visual");
  const [source, setSource] = useState("");
  const [error, setError] = useState("");
  const root = useRef<HTMLDivElement>(null);
  return (
    <div className="stack stack--compact" ref={root}>
      <div className="btn-group align-start" role="group" aria-label="Value editor view">
        <button
          type="button"
          disabled={!!error}
          className={`btn btn-sm ${mode === "visual" ? "btn-primary" : "btn-outline-secondary"}`}
          onClick={() => {
            if (!error) setMode("visual");
          }}
        >
          Visual value
        </button>
        <button
          type="button"
          className={`btn btn-sm ${mode === "yaml" ? "btn-primary" : "btn-outline-secondary"}`}
          onClick={() => {
            if (
              mode !== "yaml" &&
              Array.from(
                root.current?.querySelectorAll<
                  HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement
                >("input,select,textarea") ?? [],
              ).every((input) => input.reportValidity())
            ) {
              setSource(stringify(value ?? null));
              setMode("yaml");
            }
          }}
        >
          YAML value
        </button>
      </div>
      {mode === "visual" ? (
        <TypedField {...{ id, schema, value, onChange }} />
      ) : (
        <label className="form-label">
          Value (YAML)
          <textarea
            className="editor form-control"
            rows={10}
            spellCheck={false}
            value={source}
            ref={(node) => node?.setCustomValidity(error)}
            onChange={(e) => {
              const text = e.target.value;
              setSource(text);
              const doc = parseDocument(text, { uniqueKeys: true });
              if (doc.errors.length) setError(doc.errors.map((err) => err.message).join("\n"));
              else {
                try {
                  const next: unknown = doc.toJS();
                  JSON.stringify(next, (_key, value: unknown) => {
                    if (typeof value === "number" && !Number.isFinite(value))
                      throw new Error("Use finite numbers.");
                    return value;
                  });
                  onChange(next);
                  setError("");
                } catch (err) {
                  setError(String(err));
                }
              }
            }}
          />
        </label>
      )}
      {error ? (
        <div className="stack stack--compact">
          <p role="alert" className="field__error">
            {error}
          </p>
          <button
            type="button"
            className="btn align-start"
            onClick={() => {
              setError("");
              setSource(stringify(value ?? null));
              setMode("visual");
            }}
          >
            Return to last valid value
          </button>
        </div>
      ) : null}
    </div>
  );
}
