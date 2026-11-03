"use client";

import Link from "next/link";
import { useState } from "react";

import { DataTable, type Column } from "@/components/ui/DataTable";
import { Dialog } from "@/components/ui/Dialog";
import { Empty, Failure, Loading } from "@/components/ui/states";
import {
  useArchivePublication,
  usePublications,
} from "@/features/publications/usePublications";
import type { PublicationSummary } from "@/lib/api";
import { formatRelative } from "@/lib/format";

export function PublicationsScreen() {
  const query = usePublications();
  const archive = useArchivePublication();
  const [withdrawing, setWithdrawing] = useState<PublicationSummary | null>(null);

  const columns: Column<PublicationSummary>[] = [
    { key: "slug", header: "Entry", render: (row) => <code>{row.slug}</code> },
    { key: "status", header: "Status", render: (row) => row.status },
    {
      key: "created",
      header: "Created",
      render: (row) => formatRelative(row.created_at),
      secondary: true,
    },
    {
      key: "actions",
      header: "",
      render: (row) =>
        row.status === "published" ? (
          <div className="button-row">
            <Link href={`/catalog/${row.slug}`} className="button btn">
              View
            </Link>
            <button type="button" className="button btn" onClick={() => setWithdrawing(row)}>
              Withdraw
            </button>
          </div>
        ) : null,
    },
  ];

  return (
    <div className="stack">
      <header className="page-header">
        <h1>Publications</h1>
        <div className="button-row">
          <Link href="/publications/library" className="button btn">
            Types and presets
          </Link>
          <Link href="/publications/new" className="button btn button--primary btn-primary">
            New entry
          </Link>
        </div>
      </header>

      {query.isPending ? <Loading what="publications" /> : null}
      {query.isError ? (
        <Failure error={query.error} onRetry={() => void query.refetch()} />
      ) : null}
      {archive.isError ? <Failure error={archive.error} /> : null}

      {query.data ? (
        query.data.items.length === 0 ? (
          <Empty
            title="Nothing has been published yet."
            detail="A catalog entry is how a researcher starts a run without reading a pipeline."
            action={
              <Link href="/publications/new" className="button btn button--primary btn-primary">
                Compose one
              </Link>
            }
          />
        ) : (
          <DataTable
            caption="Publications"
            rows={query.data.items}
            columns={columns}
            rowKey={(row) => row.id}
          />
        )
      ) : null}

      <Dialog
        open={withdrawing !== null}
        title="Withdraw this entry?"
        onClose={() => setWithdrawing(null)}
      >
        <p>
          It leaves the catalog, so nobody can start a new run from it. Runs that already exist
          are untouched, and the entry can be published again.
        </p>
        <div className="dialog__actions">
          <button
            type="button"
            className="button btn button--quiet btn-ghost-secondary"
            onClick={() => setWithdrawing(null)}
          >
            Keep it
          </button>
          <button
            type="button"
            className="button btn button--danger btn-danger"
            onClick={() => {
              if (withdrawing) archive.mutate(withdrawing.id);
              setWithdrawing(null);
            }}
          >
            Withdraw
          </button>
        </div>
      </Dialog>
    </div>
  );
}
