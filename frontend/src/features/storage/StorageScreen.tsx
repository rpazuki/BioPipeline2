"use client";

/**
 * The screen a deployment starts at.
 *
 * Until a root is registered here, nothing that names a file the lab already
 * has can be submitted at all: the allowlist a fan-out is confined to is
 * empty, so every path is refused. This was the one part of the system that
 * could only be configured by writing SQL.
 *
 * The form is mostly one field of prose. Registering a root is an
 * **attestation** — a statement that everybody who can reach this share
 * through the platform already has access to it directly — and that is a
 * judgement about a filesystem the platform cannot inspect. What is being
 * recorded is not that somebody ticked a box but what they checked, so the
 * note is required and it is the largest control on the page.
 */

import { useState } from "react";

import { DataTable, type Column } from "@/components/ui/DataTable";
import { Dialog } from "@/components/ui/Dialog";
import { Field } from "@/components/ui/Field";
import { Empty, Failure, Loading } from "@/components/ui/states";
import {
  useRegisterStorageRoot,
  useStorageRootAction,
  useStorageRoots,
} from "@/features/storage/useStorage";
import type { StorageRoot } from "@/lib/api";
import { formatTimestamp } from "@/lib/format";
import { fieldErrors } from "@/lib/form";

function state(root: StorageRoot): { label: string; tone: string; detail: string } {
  if (root.revoked_at) {
    return {
      label: "withdrawn",
      tone: "neutral",
      detail: `Withdrawn ${formatTimestamp(root.revoked_at)}.`,
    };
  }
  if (!root.visible) {
    // `shared_root_mounts` skips it silently, which is right there and
    // invisible everywhere else. This is where it has to be said.
    return {
      label: "not there",
      tone: "bad",
      detail: "The platform cannot see this path. Submissions naming it will fail.",
    };
  }
  if (!root.in_use) {
    return { label: "not offered", tone: "warn", detail: "Registered, but not readable." };
  }
  return { label: "in use", tone: "good", detail: "Mounted read-only into every task." };
}

export function StorageScreen() {
  const query = useStorageRoots();
  const register = useRegisterStorageRoot();
  const action = useStorageRootAction();
  const [adding, setAdding] = useState(false);
  const [withdrawing, setWithdrawing] = useState<StorageRoot | null>(null);
  const [reason, setReason] = useState("");

  const [id, setId] = useState("");
  const [label, setLabel] = useState("");
  const [rootPath, setRootPath] = useState("");
  const [note, setNote] = useState("");

  const problems = fieldErrors(register.error, [
    "id",
    "label",
    "root_path",
    "attestation_note",
  ]);

  // Every one of these is required, and the note most of all. Said with a
  // disabled button rather than a round trip: there is no version of this
  // form where an empty attestation is a thing somebody meant.
  const complete = Boolean(id.trim() && label.trim() && rootPath.trim() && note.trim());

  function submit() {
    register.mutate(
      {
        id: id.trim(),
        label: label.trim(),
        rootPath: rootPath.trim(),
        attestationNote: note.trim(),
        readable: true,
        writable: false,
      },
      {
        onSuccess: () => {
          setAdding(false);
          setId("");
          setLabel("");
          setRootPath("");
          setNote("");
        },
      },
    );
  }

  const columns: Column<StorageRoot>[] = [
    {
      key: "label",
      header: "Share",
      render: (root) => (
        <div className="stack stack--tight">
          <span>{root.label}</span>
          <code className="muted">{root.root_path}</code>
        </div>
      ),
    },
    {
      key: "state",
      header: "State",
      render: (root) => {
        const shown = state(root);
        return (
          <div className="stack stack--tight">
            <span className={`badge badge--${shown.tone}`}>{shown.label}</span>
            <span className="muted">{shown.detail}</span>
          </div>
        );
      },
    },
    {
      key: "attestation",
      header: "Attested",
      secondary: true,
      render: (root) => (
        <div className="stack stack--tight">
          <span>{root.attested_at ? formatTimestamp(root.attested_at) : "—"}</span>
          {root.attestation_note ? (
            <span className="muted">{root.attestation_note}</span>
          ) : null}
        </div>
      ),
    },
    {
      key: "actions",
      header: "",
      render: (root) =>
        root.revoked_at ? (
          <button
            type="button"
            className="button"
            disabled={action.isPending}
            onClick={() =>
              action.mutate({
                rootId: root.id,
                kind: "reinstate",
                text: "Re-checked; access is unchanged.",
              })
            }
          >
            Reinstate
          </button>
        ) : (
          <button type="button" className="button" onClick={() => setWithdrawing(root)}>
            Withdraw
          </button>
        ),
    },
  ];

  return (
    <div className="stack">
      <header className="page-header">
        <div>
          <h1>Shared storage</h1>
          <p className="muted">
            The paths a task container may read. A pipeline names its inputs by path, and a path
            outside every root here is refused before a run starts.
          </p>
        </div>
        <button
          type="button"
          className="button button--primary"
          onClick={() => setAdding(true)}
        >
          Register a root
        </button>
      </header>

      {query.isPending ? <Loading what="storage roots" /> : null}
      {query.isError ? (
        <Failure error={query.error} onRetry={() => void query.refetch()} />
      ) : null}
      {action.isError ? <Failure error={action.error} /> : null}

      {query.data ? (
        query.data.items.length === 0 ? (
          <Empty
            title="No storage root is registered."
            detail="Until one is, nothing that names a file on the lab's own storage can be submitted."
            action={
              <button
                type="button"
                className="button button--primary"
                onClick={() => setAdding(true)}
              >
                Register a root
              </button>
            }
          />
        ) : (
          <DataTable
            caption="Shared storage roots"
            rows={query.data.items}
            columns={columns}
            rowKey={(root) => root.id}
          />
        )
      ) : null}

      <p className="muted">
        A change here reaches a worker when it next starts: mounts are resolved once per process
        rather than per task.
      </p>

      <Dialog open={adding} title="Register a storage root" onClose={() => setAdding(false)}>
        <form
          className="form stack"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            submit();
          }}
        >
          <Field
            id="root-path"
            label="Path"
            hint="Absolute, and as the machine running the workers sees it — a pipeline's {data_root}/plate.csv has to mean the same thing inside the container."
            error={problems.for("root_path")}
          >
            {(props) => (
              <input
                {...props}
                value={rootPath}
                spellCheck={false}
                placeholder="/mnt/nas01/bio-lab"
                onChange={(event) => setRootPath(event.target.value)}
              />
            )}
          </Field>

          <Field id="root-label" label="Label" error={problems.for("label")}>
            {(props) => (
              <input
                {...props}
                value={label}
                placeholder="Bio-lab share"
                onChange={(event) => setLabel(event.target.value)}
              />
            )}
          </Field>

          <Field
            id="root-id"
            label="Identifier"
            hint="Lowercase letters, digits and hyphens. Deliveries refer to a root by this."
            error={problems.for("id")}
          >
            {(props) => (
              <input
                {...props}
                value={id}
                spellCheck={false}
                placeholder="bio-lab"
                onChange={(event) => setId(event.target.value)}
              />
            )}
          </Field>

          <Field
            id="root-note"
            label="What you are attesting"
            hint="That everybody who can reach this share through the platform already has access to it directly. Write down what you checked — which share, whose members, against which access list. Nobody can reconstruct this later."
            error={problems.for("attestation_note")}
          >
            {(props) => (
              <textarea
                {...props}
                rows={4}
                value={note}
                onChange={(event) => setNote(event.target.value)}
              />
            )}
          </Field>

          {register.isError && problems.unattached.length > 0 ? (
            <div className="form__error" role="alert">
              {problems.unattached.map((message) => (
                <p key={message}>{message}</p>
              ))}
            </div>
          ) : null}

          <div className="dialog__actions">
            <button
              type="button"
              className="button button--quiet"
              onClick={() => setAdding(false)}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="button button--primary"
              disabled={register.isPending || !complete}
            >
              {register.isPending ? "Registering…" : "Register"}
            </button>
          </div>
        </form>
      </Dialog>

      <Dialog
        open={withdrawing !== null}
        title="Withdraw this root?"
        onClose={() => setWithdrawing(null)}
      >
        <p>
          Tasks stop being given <code>{withdrawing?.root_path}</code> when workers next start.
          Anything already running keeps the mount it was given. The record of who attested it
          stays.
        </p>
        <Field id="withdraw-reason" label="Why">
          {(props) => (
            <input
              {...props}
              value={reason}
              placeholder="The share was decommissioned."
              onChange={(event) => setReason(event.target.value)}
            />
          )}
        </Field>
        <div className="dialog__actions">
          <button
            type="button"
            className="button button--quiet"
            onClick={() => setWithdrawing(null)}
          >
            Keep it
          </button>
          <button
            type="button"
            className="button button--primary"
            disabled={action.isPending || !reason.trim()}
            onClick={() =>
              withdrawing &&
              action.mutate(
                { rootId: withdrawing.id, kind: "revoke", text: reason.trim() },
                {
                  onSuccess: () => {
                    setWithdrawing(null);
                    setReason("");
                  },
                },
              )
            }
          >
            Withdraw
          </button>
        </div>
      </Dialog>
    </div>
  );
}
