"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { DataTable, type Column } from "@/components/ui/DataTable";
import { Empty, Failure, Loading } from "@/components/ui/states";
import { usePipelineList } from "@/features/pipelines/usePipelines";
import type { PipelineSummary } from "@/lib/api";
import { formatRelative } from "@/lib/format";

const COLUMNS: Column<PipelineSummary>[] = [
  { key: "title", header: "Title", render: (pipeline) => pipeline.title },
  { key: "slug", header: "Slug", render: (pipeline) => <code>{pipeline.slug}</code> },
  { key: "status", header: "Status", render: (pipeline) => pipeline.status },
  {
    key: "created",
    header: "Created",
    render: (pipeline) => formatRelative(pipeline.created_at),
    secondary: true,
  },
];

export function PipelinesScreen() {
  const router = useRouter();
  // Cursor paging, forward only: the API pages by cursor because a collection
  // that grows while it is being read shifts every offset page.
  const [cursor, setCursor] = useState<string | undefined>(undefined);
  const [history, setHistory] = useState<string[]>([]);
  const query = usePipelineList(cursor);

  return (
    <div className="stack">
      <header className="page-header">
        <h1>Pipelines</h1>
        <Link href="/pipelines/new" className="button button--primary">
          New revision
        </Link>
      </header>

      {query.isPending ? <Loading what="pipelines" /> : null}
      {query.isError ? (
        <Failure error={query.error} onRetry={() => void query.refetch()} />
      ) : null}

      {query.data ? (
        query.data.items.length === 0 && history.length === 0 ? (
          <Empty
            title="No pipelines yet."
            detail="A pipeline is created by compiling its first revision."
            action={
              <Link href="/pipelines/new" className="button button--primary">
                Write one
              </Link>
            }
          />
        ) : (
          <>
            <DataTable
              caption="Pipelines"
              rows={query.data.items}
              columns={COLUMNS}
              rowKey={(pipeline) => pipeline.id}
              onOpen={(pipeline) => router.push(`/pipelines/${pipeline.id}`)}
            />
            <div className="button-row">
              <button
                type="button"
                className="button"
                disabled={history.length === 0}
                onClick={() => {
                  setCursor(history[history.length - 1]);
                  setHistory((past) => past.slice(0, -1));
                }}
              >
                Previous
              </button>
              <button
                type="button"
                className="button"
                disabled={!query.data.next_cursor}
                onClick={() => {
                  const next = query.data.next_cursor;
                  if (!next) return;
                  setHistory((past) => [...past, cursor ?? ""]);
                  setCursor(next);
                }}
              >
                Next
              </button>
            </div>
          </>
        )
      ) : null}
    </div>
  );
}
