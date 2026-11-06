"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Dialog } from "@/components/ui/Dialog";
import { Failure, StatusReport } from "@/components/ui/states";
import { useApi, useSession } from "@/features/auth/session";

/** Confirm an administrator's deletion and refresh affected resource lists. */
export function DeleteResource({
  endpoint,
  name,
  description,
  onDeleted,
}: {
  endpoint: string;
  name: string;
  description: string;
  onDeleted?: () => void;
}) {
  const client = useApi();
  const cache = useQueryClient();
  const { role } = useSession();
  const [open, setOpen] = useState(false);
  const remove = useMutation({
    mutationFn: () => client.del(endpoint),
    onSuccess: () => {
      setOpen(false);
      void cache.invalidateQueries();
      onDeleted?.();
    },
  });
  if (role !== "admin") return null;
  return (
    <>
      <button
        type="button"
        className="btn btn-outline-danger"
        aria-label={`Delete ${name}`}
        onClick={() => {
          remove.reset();
          setOpen(true);
        }}
      >
        Delete
      </button>
      {remove.isSuccess ? (
        <StatusReport tone="success" title="Deletion recorded">
          File cleanup progress and deletion history are available on the Audit page.
        </StatusReport>
      ) : null}
      <Dialog
        open={open}
        title={`Delete ${name}?`}
        onClose={() => !remove.isPending && setOpen(false)}
      >
        <p>{description}</p>
        <p>The audit record will be kept.</p>
        {remove.isError ? <Failure error={remove.error} /> : null}
        <div className="dialog__actions">
          <button
            type="button"
            className="btn"
            disabled={remove.isPending}
            onClick={() => setOpen(false)}
          >
            Keep it
          </button>
          <button
            type="button"
            className="btn btn-danger"
            disabled={remove.isPending}
            aria-busy={remove.isPending}
            onClick={() => remove.mutate()}
          >
            {remove.isPending ? "Deleting…" : "Confirm deletion"}
          </button>
        </div>
      </Dialog>
    </>
  );
}
