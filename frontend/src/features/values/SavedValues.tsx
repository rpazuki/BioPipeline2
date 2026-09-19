"use client";

/**
 * Keeping a filled-in value, and using it again.
 *
 * A replicate rule is four fields, two of them regular expressions, and the
 * researcher who runs the same analysis every week retypes all four every
 * week. This is the picker that ends that, plus the button that puts one in
 * it.
 *
 * A saved value that no longer fits is **shown and disabled, with the
 * reason**, not hidden. Its schema was frozen when it was saved and the
 * field's when the entry was published; when those disagree the researcher
 * needs to know their rule is no longer accepted here, not to wonder where it
 * went.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { useApi } from "@/features/auth/session";
import { savedValues, type SavedValue } from "@/lib/api";
import { ApiError } from "@/lib/errors";

function keyFor(entry: string, fieldKey: string) {
  return ["saved-values", entry, fieldKey] as const;
}

export function SavedValues({
  entry,
  fieldKey,
  value,
  onUse,
}: {
  entry: string;
  fieldKey: string;
  value: unknown;
  onUse: (value: unknown) => void;
}) {
  const client = useApi();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [naming, setNaming] = useState(false);

  const saved = useQuery({
    queryKey: keyFor(entry, fieldKey),
    queryFn: () => savedValues.list(client, { entry, fieldKey }),
  });

  const keep = useMutation({
    mutationFn: (label: string) =>
      savedValues.save(client, entry, { fieldKey, name: label, value }),
    onSuccess: () => {
      setName("");
      setNaming(false);
      void queryClient.invalidateQueries({ queryKey: keyFor(entry, fieldKey) });
    },
  });

  const items: SavedValue[] = saved.data?.items ?? [];

  return (
    <div className="saved">
      {items.length > 0 ? (
        <div className="button-row">
          {items.map((item) => (
            <button
              key={item.id}
              type="button"
              className="button button--quiet"
              disabled={!item.usable}
              title={item.unusable_reason ?? undefined}
              onClick={() => onUse(item.value)}
            >
              {item.name}
            </button>
          ))}
        </div>
      ) : null}

      {items.some((item) => !item.usable) ? (
        <p className="muted">{items.find((item) => !item.usable)?.unusable_reason}</p>
      ) : null}

      {naming ? (
        <div className="button-row">
          <input
            type="text"
            aria-label="Name for this value"
            placeholder="Weekly plates"
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
          <button
            type="button"
            className="button button--primary"
            disabled={!name.trim() || keep.isPending}
            onClick={() => keep.mutate(name.trim())}
          >
            {keep.isPending ? "Saving…" : "Keep it"}
          </button>
          <button type="button" className="button" onClick={() => setNaming(false)}>
            Cancel
          </button>
        </div>
      ) : (
        <button type="button" className="button button--quiet" onClick={() => setNaming(true)}>
          Save this value
        </button>
      )}

      {keep.isError ? (
        <p className="field__error" role="alert">
          {keep.error instanceof ApiError ? keep.error.message : "It could not be saved."}
        </p>
      ) : null}
    </div>
  );
}
