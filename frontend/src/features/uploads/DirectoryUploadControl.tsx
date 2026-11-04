"use client";

import { useEffect, useRef, useState } from "react";
import type { InputHTMLAttributes } from "react";
import { useApi } from "@/features/auth/session";
import { StatusReport } from "@/components/ui/states";
import { uploads, type Upload } from "@/lib/api";
import { uploadFile } from "@/lib/upload";
import { formatBytes } from "@/lib/format";

export function DirectoryUploadControl({
  id,
  value,
  onChange,
  sources,
  describedBy,
  invalid,
}: {
  id: string;
  value: string;
  onChange: (value: string) => void;
  sources: string[];
  describedBy?: string | undefined;
  invalid?: boolean | undefined;
}) {
  const client = useApi();
  const methods = sources.includes("upload")
    ? ["folder", "zip", ...sources.filter((item) => item !== "upload")]
    : sources;
  const [method, setMethod] = useState(
    value && !value.startsWith("upload:") && methods.includes("shared")
      ? "shared"
      : (methods[0] ?? "shared"),
  );
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState({ sent: 0, total: 0, assembling: false });
  const [error, setError] = useState("");
  const [chosenName, setChosenName] = useState("");
  const abort = useRef<AbortController | null>(null);
  const partial = useRef(new Map<string, Upload>());
  const assembly = useRef<{ key: string; id: string } | null>(null);
  useEffect(() => () => abort.current?.abort(), []);

  async function send(files: File[]) {
    if (!files.length) return;
    const total = files.reduce((sum, file) => sum + file.size, 0);
    if (
      method === "folder" &&
      (files.length > (client.settings.upload_directory_max_files ?? 20_000) ||
        total > (client.settings.upload_directory_max_bytes ?? 20 * 1024 ** 3))
    ) {
      setError(
        "This folder exceeds the directory upload limit. Use registered shared storage.",
      );
      return;
    }
    const controller = new AbortController();
    abort.current = controller;
    setBusy(true);
    setError("");
    let sent = 0;
    setProgress({ sent: 0, total, assembling: false });
    const name =
      method === "zip"
        ? files[0]!.name.replace(/\.zip$/i, "") || "input"
        : (files[0]!.webkitRelativePath ?? "").split("/")[0] || "input";
    const fingerprint = JSON.stringify([
      method,
      files.map((file) => [file.webkitRelativePath || file.name, file.size, file.lastModified]),
    ]);
    if (assembly.current?.key !== fingerprint)
      assembly.current = { key: fingerprint, id: crypto.randomUUID() };
    try {
      const members = [];
      for (const file of files) {
        const key = JSON.stringify([
          file.webkitRelativePath || file.name,
          file.size,
          file.lastModified,
        ]);
        const resume = partial.current.get(key);
        const completed = await uploadFile(client, file, {
          ...(resume ? { resume } : {}),
          signal: controller.signal,
          onOpened: (upload) => partial.current.set(key, upload),
          onProgress: (next) =>
            setProgress({ sent: sent + next.sent, total, assembling: false }),
        });
        partial.current.set(key, completed);
        sent += file.size;
        members.push({
          path: (file.webkitRelativePath ?? "").split("/").slice(1).join("/") || file.name,
          upload_id: completed.id,
        });
      }
      controller.signal.throwIfAborted();
      setProgress({ sent: total, total, assembling: true });
      const completed = await uploads.directory(client, {
        request_id: assembly.current!.id,
        name,
        ...(method === "zip" ? { zip_upload_id: members[0]!.upload_id } : { files: members }),
      });
      if (!controller.signal.aborted) {
        setChosenName(name);
        onChange(completed.reference ?? "");
      }
    } catch (failure) {
      if (!controller.signal.aborted)
        setError(
          failure instanceof Error ? failure.message : "The directory could not be prepared.",
        );
    } finally {
      setBusy(false);
      abort.current = null;
    }
  }

  if (busy)
    return (
      <div className="stack stack--tight">
        <StatusReport
          tone="working"
          title={
            progress.assembling
              ? "Checking and preparing the directory…"
              : "Uploading directory contents…"
          }
        >
          <progress
            className="progress"
            aria-label="Directory upload progress"
            max={progress.total || 1}
            value={progress.sent}
          />
          {formatBytes(progress.sent)} of {formatBytes(progress.total)}
        </StatusReport>
        {!progress.assembling ? (
          <button type="button" className="button btn" onClick={() => abort.current?.abort()}>
            Stop
          </button>
        ) : null}
      </div>
    );
  if (value.startsWith("upload:"))
    return (
      <div className="stack stack--tight">
        <StatusReport tone="success" title={`${chosenName || "Uploaded directory"} is ready`} />
        <button type="button" className="button btn" onClick={() => onChange("")}>
          Choose a different directory
        </button>
      </div>
    );
  if (methods.length === 1 && methods[0] === "shared")
    return (
      <input
        id={id}
        type="text"
        className="form-control"
        aria-label="Shared directory path"
        aria-describedby={describedBy}
        aria-invalid={invalid}
        value={value}
        spellCheck={false}
        onChange={(event) => onChange(event.target.value)}
        placeholder="/mnt/registered-share/folder"
      />
    );
  return (
    <div className="stack stack--tight">
      {method !== "shared" ? (
        <p className="field__hint">
          Directories may contain up to {client.settings.upload_directory_max_files ?? 20_000}{" "}
          files and {formatBytes(client.settings.upload_directory_max_bytes ?? 20 * 1024 ** 3)}{" "}
          after extraction.
        </p>
      ) : null}
      <select
        id={id}
        className="form-select"
        aria-label="Directory input method"
        aria-invalid={invalid}
        aria-describedby={describedBy}
        value={method}
        onChange={(event) => {
          setMethod(event.target.value);
          setError("");
          onChange("");
        }}
      >
        {methods.map((item) => (
          <option key={item} value={item}>
            {{
              folder: "Upload a folder",
              zip: "Upload a ZIP archive",
              shared: "Registered shared storage",
            }[item] ?? item}
          </option>
        ))}
      </select>
      {method === "shared" ? (
        <input
          className="form-control"
          type="text"
          aria-label="Shared directory path"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder="/mnt/registered-share/folder"
        />
      ) : (
        <input
          key={method}
          className="form-control"
          type="file"
          aria-label={method === "folder" ? "Choose folder" : "Choose ZIP file"}
          accept={method === "zip" ? ".zip,application/zip" : undefined}
          multiple={method === "folder"}
          {...(method === "folder"
            ? ({ webkitdirectory: "", directory: "" } as InputHTMLAttributes<HTMLInputElement>)
            : {})}
          onChange={(event) => void send(Array.from(event.target.files ?? []))}
        />
      )}
      {error ? (
        <StatusReport tone="error" title={error}>
          <p>Select the same files to resume an interrupted transfer.</p>
        </StatusReport>
      ) : null}
    </div>
  );
}
