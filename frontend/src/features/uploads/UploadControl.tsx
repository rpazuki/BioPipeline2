"use client";

/**
 * Choosing a file for a submission field.
 *
 * The control the form's hint has been apologising for: until now a `file`
 * input could only be a path on a share, so anyone whose data was on their own
 * machine had to get it onto the share first, by whatever means their lab had.
 *
 * Three things it has to say and does not leave to be guessed.
 *
 * **Where the file is going to come from.** A field that accepts both a share
 * and an upload offers both, side by side, rather than picking one for the
 * researcher — the answer depends on where their data already is, which is not
 * something the platform knows.
 *
 * **That a transfer is resumable.** A failure keeps the upload, and the retry
 * continues from the byte the server has rather than starting again. Saying so
 * is most of the value; a researcher who thinks a failure means four hours
 * again will close the tab.
 *
 * **Where the very large files go.** Above the deployment's ceiling the honest
 * answer is not this control at all (ADR 0033) — it is the share, with the
 * tools built for moving data at that size.
 */

import { useQuery } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { useApi } from "@/features/auth/session";
import { uploads, type Upload } from "@/lib/api";
import { ApiError } from "@/lib/errors";
import { formatBytes } from "@/lib/format";
import { uploadFile, type Progress } from "@/lib/upload";

const REFERENCE = "upload:";

export function isUploadReference(value: string): boolean {
  return value.startsWith(REFERENCE);
}

/** What the researcher is doing right now, which is what decides the controls. */
type Phase =
  | { kind: "idle" }
  | { kind: "sending"; progress: Progress; file: string }
  | { kind: "failed"; message: string; file: string };

export function UploadControl({
  id,
  value,
  onChange,
  sources,
  describedBy,
}: {
  id: string;
  value: string;
  onChange: (value: string) => void;
  sources: string[];
  describedBy?: string | undefined;
}) {
  const client = useApi();
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const abort = useRef<AbortController | null>(null);
  const chosen = isUploadReference(value);
  const sharedToo = sources.includes("shared");

  // A reference with no transfer behind it: the form was prefilled, from
  // "submit this again" or a draft. Ask what it was rather than showing a
  // researcher the words "upload:" and a UUID.
  const uploaded = useQuery({
    queryKey: ["upload", value],
    queryFn: () => uploads.get(client, value.slice(REFERENCE.length)),
    enabled: chosen,
    staleTime: Infinity,
  });

  async function send(file: File) {
    const controller = new AbortController();
    abort.current = controller;
    setPhase({ kind: "sending", progress: { sent: 0, total: file.size }, file: file.name });
    try {
      const finished: Upload = await uploadFile(client, file, {
        signal: controller.signal,
        onProgress: (progress) => setPhase({ kind: "sending", progress, file: file.name }),
      });
      setPhase({ kind: "idle" });
      onChange(finished.reference ?? "");
    } catch (error) {
      if (controller.signal.aborted) {
        setPhase({ kind: "idle" });
        return;
      }
      setPhase({
        kind: "failed",
        file: file.name,
        message:
          error instanceof ApiError
            ? error.message
            : "The file could not be sent. Choosing it again continues where this stopped.",
      });
    } finally {
      abort.current = null;
    }
  }

  if (phase.kind === "sending") {
    const { sent, total } = phase.progress;
    const percent = total === 0 ? 0 : Math.round((sent / total) * 100);
    return (
      <div className="stack stack--tight">
        <progress
          className="progress"
          value={sent}
          max={total}
          aria-label={`Sending ${phase.file}`}
        >
          {percent}%
        </progress>
        <p className="muted">
          Sending {phase.file} — {formatBytes(sent)} of {formatBytes(total)}.
        </p>
        <button type="button" className="button" onClick={() => abort.current?.abort()}>
          Stop
        </button>
      </div>
    );
  }

  if (chosen) {
    return (
      <div className="stack stack--tight">
        <p id={id} tabIndex={-1}>
          <strong>{uploaded.data?.filename ?? "A file"}</strong>{" "}
          <span className="muted">
            {uploaded.data ? `(${formatBytes(uploaded.data.received_bytes)})` : "uploaded"}
          </span>
        </p>
        <button type="button" className="button" onClick={() => onChange("")}>
          Choose a different file
        </button>
      </div>
    );
  }

  return (
    <div className="stack stack--tight">
      {phase.kind === "failed" ? (
        <p className="field__error" role="alert">
          {phase.message} Choosing {phase.file} again continues from where it stopped rather
          than starting over.
        </p>
      ) : null}
      <input
        id={id}
        type="file"
        aria-describedby={describedBy}
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) void send(file);
        }}
      />
      {sharedToo ? (
        <details>
          <summary className="muted">…or name a file already on the share</summary>
          <input
            type="text"
            aria-label="Path on a shared root"
            spellCheck={false}
            defaultValue=""
            onBlur={(event) => {
              const path = event.target.value.trim();
              if (path) onChange(path);
            }}
          />
          <p className="muted">
            The better route for very large files: put it on the share with the tools built for
            that, and name it here.
          </p>
        </details>
      ) : null}
    </div>
  );
}
