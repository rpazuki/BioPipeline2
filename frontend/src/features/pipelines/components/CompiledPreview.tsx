/**
 * What a document will actually do, before it becomes a revision it cannot.
 *
 * A revision is immutable once stored, so this is the last point at which an
 * author can see the input contract and the stage graph and change their mind.
 */

import type { CompilePreviewResponse } from "@/lib/api";

export function CompiledPreview({ preview }: { preview: CompilePreviewResponse }) {
  if (!preview.ok) return null;
  // Optional on the wire because each has a server-side default; a compiled
  // pipeline with no inputs sends no `inputs` key at all.
  const inputs = preview.inputs ?? [];
  const stages = preview.stages ?? [];

  return (
    <div className="stack">
      <section className="panel">
        <h3>Inputs</h3>
        {inputs.length === 0 ? (
          <p className="muted">This pipeline takes no submitted values.</p>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <caption className="visually-hidden">Declared inputs</caption>
              <thead>
                <tr>
                  <th scope="col">Key</th>
                  <th scope="col">Accepts</th>
                  <th scope="col">From</th>
                  <th scope="col">Required</th>
                </tr>
              </thead>
              <tbody>
                {inputs.map((input) => (
                  <tr key={input.key}>
                    <td>
                      <code>{input.key}</code>
                    </td>
                    <td>
                      {input.accept}
                      {input.type_ref ? (
                        <span className="muted"> · {input.type_ref}</span>
                      ) : null}
                    </td>
                    {/* How a file may be supplied: uploaded, chosen from shared
                        storage, or fetched from a URL. It decides which control
                        a submission form can offer. */}
                    <td>{(input.sources ?? []).join(", ") || "—"}</td>
                    <td>{input.required ? "yes" : "no"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {inputs.some((input) => input.help) ? (
          <dl className="detail-list">
            {inputs
              .filter((input) => input.help)
              .map((input) => (
                <div key={input.key} className="detail-list__pair">
                  <dt>{input.key}</dt>
                  <dd>{input.help}</dd>
                </div>
              ))}
          </dl>
        ) : null}
      </section>

      <section className="panel">
        <h3>Stages</h3>
        <ol className="stage-list">
          {stages.map((stage) => (
            <li key={stage.key} className="stage">
              <div className="stage__head">
                <code>{stage.key}</code>
                <span className="muted">{stage.task_class}</span>
                {stage.fanout !== "none" ? (
                  <span className="tag">fan-out: {stage.fanout}</span>
                ) : null}
              </div>
              <p className="muted">{(stage.steps ?? []).join(" \u2192 ")}</p>
              {(stage.needs ?? []).length > 0 ? (
                <p className="muted">after {(stage.needs ?? []).join(", ")}</p>
              ) : null}
              {(stage.outputs ?? []).length > 0 ? (
                <p className="muted">produces {(stage.outputs ?? []).join(", ")}</p>
              ) : null}
            </li>
          ))}
        </ol>
        <p className="muted">
          Graph hash <code className="wrap">{preview.graph_hash}</code>
        </p>
      </section>
    </div>
  );
}
