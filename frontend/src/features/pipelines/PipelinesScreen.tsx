"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Dialog } from "@/components/ui/Dialog";
import { useApi } from "@/features/auth/session";

import { DataTable, type Column } from "@/components/ui/DataTable";
import { Empty, Failure, Loading } from "@/components/ui/states";
import { usePipelineList } from "@/features/pipelines/usePipelines";
import { ComponentsScreen } from "@/features/pipelines/ComponentsScreen";
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
  const [tab, setTab] = useState<"pipelines" | "components">("pipelines");
  return (
    <div className="stack">
      <h1>Workflow definitions</h1>
      <div role="tablist" aria-label="Definition type" className="button-row">
        <button
          role="tab"
          id="pipelines-tab"
          aria-controls="definitions-panel"
          aria-selected={tab === "pipelines"}
          className="button btn"
          onClick={() => setTab("pipelines")}
        >
          Pipelines
        </button>
        <button
          role="tab"
          id="components-tab"
          aria-controls="definitions-panel"
          aria-selected={tab === "components"}
          className="button btn"
          onClick={() => setTab("components")}
        >
          Components
        </button>
      </div>
      <div role="tabpanel" id="definitions-panel" aria-labelledby={`${tab}-tab`}>
        {tab === "pipelines" ? <PipelineList /> : <ComponentsScreen />}
      </div>
    </div>
  );
}

function PipelineList() {
  const router = useRouter();
  const client = useApi();
  const cache = useQueryClient();
  const [withdrawing, setWithdrawing] = useState<PipelineSummary | null>(null);
  const archive = useMutation({
    mutationFn: (id: string) => client.post(`/pipelines/${id}/archive`),
    onSuccess: () => {
      setWithdrawing(null);
      void cache.invalidateQueries({ queryKey: ["pipelines"] });
    },
  });
  // Cursor paging, forward only: the API pages by cursor because a collection
  // that grows while it is being read shifts every offset page.
  const [cursor, setCursor] = useState<string | undefined>(undefined);
  const [history, setHistory] = useState<string[]>([]);
  const query = usePipelineList(cursor);

  return (
    <div className="stack">
      <header className="page-header">
        <div>
          <h2>Pipelines</h2>
          <p>
            Complete workflows with inputs, stages and outputs. A stage can use a component or
            define its calls directly.
          </p>
        </div>
        <Link href="/pipelines/new" className="button btn button--primary btn-primary">
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
              <Link href="/pipelines/new" className="button btn button--primary btn-primary">
                Write one
              </Link>
            }
          />
        ) : (
          <>
            <DataTable
              caption="Pipelines"
              rows={query.data.items}
              columns={[
                ...COLUMNS,
                {
                  key: "actions",
                  header: "Actions",
                  render: (pipeline) => (
                    <button
                      type="button"
                      className="button btn"
                      onClick={(event) => {
                        event.stopPropagation();
                        archive.reset();
                        setWithdrawing(pipeline);
                      }}
                      onKeyDown={(event) => event.stopPropagation()}
                    >
                      Archive
                    </button>
                  ),
                },
              ]}
              rowKey={(pipeline) => pipeline.id}
              onOpen={(pipeline) => router.push(`/pipelines/${pipeline.id}`)}
            />
            <div className="button-row">
              <button
                type="button"
                className="button btn"
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
                className="button btn"
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
      <Dialog
        open={withdrawing !== null}
        title="Archive this pipeline?"
        onClose={() => setWithdrawing(null)}
      >
        <p>
          Remove {withdrawing?.title} from the active pipeline list. Saved revisions,
          publications and runs remain available. Withdraw a publication separately to remove it
          from the catalog.
        </p>
        {archive.isError ? <Failure error={archive.error} /> : null}
        <div className="dialog__actions">
          <button
            type="button"
            className="button btn"
            disabled={archive.isPending}
            onClick={() => setWithdrawing(null)}
          >
            Keep pipeline
          </button>
          <button
            type="button"
            className="button btn btn-danger"
            aria-busy={archive.isPending}
            disabled={archive.isPending}
            onClick={() => withdrawing && archive.mutate(withdrawing.id)}
          >
            {archive.isPending ? "Archiving…" : "Archive pipeline"}
          </button>
        </div>
      </Dialog>
    </div>
  );
}
