/**
 * Every endpoint this frontend uses, typed from the committed contract.
 *
 * The names below are re-exports of generated schema types, not copies. If the
 * backend renames a field or adds a run status, `npm run typecheck` fails here
 * rather than a badge quietly rendering blank in production.
 *
 * Endpoints the plan calls for and the backend does not serve yet — catalog,
 * publications, schedules, saved values, type library, the environment
 * browser, log streaming, artifact download, chunked upload — are absent
 * rather than stubbed. A screen built on a mock is a screen nobody can trust.
 */

import type { ApiClient } from "@/lib/client";
import type { components } from "@/generated/api-types";

type Schemas = components["schemas"];

export type ArtifactSummary = Schemas["ArtifactSummary"];
export type ClientConfigResponse = Schemas["ClientConfigResponse"];
export type CompilePreviewResponse = Schemas["CompilePreviewResponse"];
export type DeliveryStatus = Schemas["DeliveryStatus"];
export type DeliverySummary = Schemas["DeliverySummary"];
export type DiagnosticResponse = Schemas["DiagnosticResponse"];
export type CompiledInput = Schemas["CompiledInputResponse"];
export type CompiledOutput = Schemas["CompiledOutputResponse"];
export type InputSourceMode = Schemas["InputSourceMode"];
export type PipelineSummary = Schemas["PipelineSummary"];
export type RevisionDetail = Schemas["RevisionDetail"];
export type RevisionResponse = Schemas["RevisionResponse"];
export type RunDetail = Schemas["RunDetail"];
export type RunStatus = Schemas["RunStatus"];
export type RunSummary = Schemas["RunSummary"];
export type SessionResponse = Schemas["SessionResponse"];
export type SubmitRunResponse = Schemas["SubmitRunResponse"];
export type TaskStatus = Schemas["TaskStatus"];
export type TaskSummary = Schemas["TaskSummary"];
export type UserRole = Schemas["UserRole"];

export type Page<T> = { items: T[]; next_cursor?: string | null; total?: number | null };

/**
 * Run statuses nothing further will happen to.
 *
 * Derived from the union rather than written out, so a status added to the
 * backend must be classified here before this file compiles — the alternative
 * is a run page that polls a finished run forever, or stops polling a live one.
 */
const TERMINAL: Record<RunStatus, boolean> = {
  queued: false,
  running: false,
  blocked: false,
  cancel_requested: false,
  succeeded: true,
  failed: true,
  cancelled: true,
};

export function isTerminal(status: RunStatus): boolean {
  return TERMINAL[status];
}

// --- auth -----------------------------------------------------------------

export const auth = {
  session: (client: ApiClient, signal?: AbortSignal) =>
    client.get<SessionResponse>("/auth/session", signal ? { signal } : {}),

  login: (client: ApiClient, email: string, password: string) =>
    client.post<SessionResponse>("/auth/login", { body: { email, password } }),

  logout: (client: ApiClient) => client.post<void>("/auth/logout"),

  changePassword: (client: ApiClient, current: string, replacement: string) =>
    client.post<void>("/auth/change-password", {
      body: { current_password: current, new_password: replacement },
    }),
};

// --- pipelines ------------------------------------------------------------

export const pipelines = {
  list: (client: ApiClient, options: { cursor?: string; limit?: number } = {}) =>
    client.get<Page<PipelineSummary>>("/pipelines", {
      query: { cursor: options.cursor, limit: options.limit },
    }),

  revisions: (client: ApiClient, pipelineId: string) =>
    client.get<Page<RevisionResponse>>(`/pipelines/${pipelineId}/revisions`),

  /** One revision, with the contract a submission against it must satisfy. */
  revision: (client: ApiClient, revisionId: string) =>
    client.get<RevisionDetail>(`/pipelines/revisions/${revisionId}`),

  compilePreview: (
    client: ApiClient,
    sourceText: string,
    values: Record<string, unknown> = {},
  ) =>
    client.post<CompilePreviewResponse>("/pipelines/compile-preview", {
      body: { source_text: sourceText, values },
    }),

  createRevision: (client: ApiClient, sourceText: string, title?: string) =>
    client.post<RevisionResponse>("/pipelines/revisions", {
      body: { source_text: sourceText, ...(title ? { title } : {}) },
    }),
};

// --- runs -----------------------------------------------------------------

export const runs = {
  list: (client: ApiClient, options: { status?: string; limit?: number } = {}) =>
    client.get<Page<RunSummary>>("/runs", {
      query: { status_filter: options.status, limit: options.limit },
    }),

  get: (client: ApiClient, runId: string) => client.get<RunDetail>(`/runs/${runId}`),

  tasks: (client: ApiClient, runId: string) =>
    client.get<Page<TaskSummary>>(`/runs/${runId}/tasks`),

  artifacts: (client: ApiClient, runId: string) =>
    client.get<Page<ArtifactSummary>>(`/runs/${runId}/artifacts`),

  deliveries: (client: ApiClient, runId: string) =>
    client.get<Page<DeliverySummary>>(`/runs/${runId}/deliveries`),

  cancel: (client: ApiClient, runId: string) =>
    client.post<RunSummary>(`/runs/${runId}/cancel`),

  /**
   * Submit a run.
   *
   * The idempotency key is generated per *attempt at submitting*, not per
   * click: a retry after a dropped connection must carry the same key, or a
   * day of alignment runs twice.
   */
  submit: (
    client: ApiClient,
    revisionId: string,
    values: Record<string, unknown>,
    idempotencyKey: string,
  ) =>
    client.post<SubmitRunResponse>("/runs", {
      body: { pipeline_revision_id: revisionId, values },
      headers: { "Idempotency-Key": idempotencyKey },
    }),
};
