"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Failure, StatusReport } from "@/components/ui/states";
import { useApi } from "@/features/auth/session";
import { artifacts } from "@/lib/api";
import { formatBytes } from "@/lib/format";

interface Bundle {
  id: string;
  run_id: string;
  status: "pending" | "working" | "ready" | "failed" | "expired";
  total_bytes: number;
  completed_bytes: number;
  artifact_id: string | null;
  message: string | null;
}

export function ResultBundle({ runId, live }: { runId: string; live: boolean }) {
  const client = useApi();
  const queries = useQueryClient();
  const [jobId, setJobId] = useState<string | null>(null);
  const query = useQuery({
    queryKey: ["result-bundle", runId, jobId],
    queryFn: () => client.get<Bundle>(`/runs/${runId}/bundles/${jobId}`),
    enabled: !!jobId,
    refetchInterval: (current) =>
      ["pending", "working"].includes(current.state.data?.status ?? "") ? 1500 : false,
  });
  const prepare = useMutation({
    mutationFn: () => client.post<Bundle>(`/runs/${runId}/bundles`, { body: {} }),
    onSuccess: (job) => {
      queries.setQueryData(["result-bundle", runId, job.id], job);
      setJobId(job.id);
    },
  });
  const job = query.data;
  const working = job?.status === "pending" || job?.status === "working";
  return (
    <div className="stack stack--tight">
      {job?.status === "ready" && job.artifact_id ? (
        <a
          className="button btn btn-primary"
          download
          href={artifacts.downloadHref(client, job.artifact_id)}
        >
          Download results ZIP
        </a>
      ) : (
        <button
          type="button"
          className="button btn btn-primary"
          disabled={live || working || prepare.isPending}
          aria-busy={working || prepare.isPending}
          onClick={() => prepare.mutate()}
        >
          {working ? "Preparing ZIP…" : "Prepare results ZIP"}
        </button>
      )}
      {live ? (
        <p className="muted">The result ZIP becomes available when the run finishes.</p>
      ) : null}
      {working ? (
        <StatusReport
          tone="working"
          title={
            job.status === "pending"
              ? "Waiting for the delivery service"
              : "Preparing results ZIP"
          }
        >
          <progress
            className="progress"
            aria-label="ZIP preparation progress"
            max={job.total_bytes || 1}
            value={job.completed_bytes}
          />
          {formatBytes(job.completed_bytes)} of {formatBytes(job.total_bytes)}
        </StatusReport>
      ) : null}
      {job?.status === "failed" || job?.status === "expired" ? (
        <StatusReport
          tone={job.status === "failed" ? "error" : "warning"}
          title={job.message ?? "The ZIP could not be prepared."}
        />
      ) : null}
      {prepare.isError ? <Failure error={prepare.error} /> : null}
      {query.isError ? (
        <Failure error={query.error} onRetry={() => void query.refetch()} />
      ) : null}
    </div>
  );
}
