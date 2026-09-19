/**
 * Every endpoint this frontend uses, typed from the committed contract.
 *
 * The names below are re-exports of generated schema types, not copies. If the
 * backend renames a field or adds a run status, `npm run typecheck` fails here
 * rather than a badge quietly rendering blank in production.
 *
 * Endpoints the plan calls for and the backend does not serve yet — saved
 * values, the type library, the environment browser, log streaming — are
 * absent rather than stubbed. A screen built on a mock is a screen nobody can
 * trust.
 */

import type { ApiClient } from "@/lib/client";
import type { components } from "@/generated/api-types";

type Schemas = components["schemas"];

export type ArtifactDetail = Schemas["ArtifactDetail"];
export type AttemptSummary = Schemas["AttemptSummary"];
export type TaskLog = Schemas["TaskLogResponse"];
export type ArtifactFile = Schemas["ArtifactFile"];
export type ArtifactSummary = Schemas["ArtifactSummary"];
export type StorageRoot = Schemas["StorageRootResponse"];
export type ClientConfigResponse = Schemas["ClientConfigResponse"];
export type CompilePreviewResponse = Schemas["CompilePreviewResponse"];
export type DeliveryStatus = Schemas["DeliveryStatus"];
export type DeliverySummary = Schemas["DeliverySummary"];
export type DiagnosticResponse = Schemas["DiagnosticResponse"];
export type BindableTarget = Schemas["BindableTargetResponse"];
export type BindingTarget = Schemas["BindingTarget"];
export type CatalogDetail = Schemas["CatalogDetail"];
export type CatalogSummary = Schemas["CatalogSummary"];
export type CompiledInput = Schemas["CompiledInputResponse"];
export type CompiledOutput = Schemas["CompiledOutputResponse"];
export type InputSourceMode = Schemas["InputSourceMode"];
export type PipelineSummary = Schemas["PipelineSummary"];
export type PrimitiveType = Schemas["PrimitiveType"];
export type PublicationField = Schemas["PublicationFieldResponse"];
export type PublicationRevisionResponse = Schemas["PublicationRevisionResponse"];
export type PublicationSummary = Schemas["PublicationSummary"];
export type RevisionDetail = Schemas["RevisionDetail"];
export type RevisionResponse = Schemas["RevisionResponse"];
export type RunDetail = Schemas["RunDetail"];
export type RunStatus = Schemas["RunStatus"];
export type RunSummary = Schemas["RunSummary"];
export type RunTrigger = Schemas["RunTrigger"];
export type CatchupPolicy = Schemas["CatchupPolicy"];
export type DstPolicy = Schemas["DstPolicy"];
export type FireOutcome = Schemas["FireOutcome"];
export type OverlapPolicy = Schemas["OverlapPolicy"];
export type ScheduleDetail = Schemas["ScheduleDetail"];
export type ScheduleEvent = Schemas["ScheduleEventResponse"];
export type ScheduleFire = Schemas["ScheduleFireResponse"];
export type ScheduleStatus = Schemas["ScheduleStatus"];
export type ScheduleSummary = Schemas["ScheduleSummary"];
export type SessionResponse = Schemas["SessionResponse"];
export type SubmitRunResponse = Schemas["SubmitRunResponse"];
export type TaskStatus = Schemas["TaskStatus"];
export type TaskSummary = Schemas["TaskSummary"];
export type EnvironmentSummary = Schemas["EnvironmentResponse"];
export type EnvironmentDetail = Schemas["EnvironmentDetail"];
export type GenerationSummary = Schemas["GenerationResponse"];
export type InstalledPackage = Schemas["PackageResponse"];
export type PackageOperation = Schemas["PackageOperationResponse"];
export type Introspection = Schemas["IntrospectionResponse"];
export type RunEnvironment = Schemas["RunEnvironment"];
export type SavedValue = Schemas["SavedValueResponse"];
export type Upload = Schemas["UploadResponse"];
export type UploadStatus = Schemas["UploadStatus"];
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

  /** Everything a publication field could attach to in this revision. */
  bindable: (client: ApiClient, revisionId: string) =>
    client.get<Page<BindableTarget>>(`/pipelines/revisions/${revisionId}/bindable`),

  createRevision: (client: ApiClient, sourceText: string, title?: string) =>
    client.post<RevisionResponse>("/pipelines/revisions", {
      body: { source_text: sourceText, ...(title ? { title } : {}) },
    }),
};

// --- publications (admin) -------------------------------------------------

export interface PublicationFieldInput {
  key: string;
  label: string;
  binding: {
    target: BindingTarget;
    stage?: string | null;
    step?: string | null;
    binding_key: string;
  };
  field_type: PrimitiveType;
  required: boolean;
  help_text?: string | null;
  ui_group?: string | null;
  default_value?: unknown;
}

export const publications = {
  list: (client: ApiClient) => client.get<Page<PublicationSummary>>("/publications"),

  createRevision: (
    client: ApiClient,
    input: {
      slug: string;
      pipelineRevisionId: string;
      title: string;
      description?: string;
      fields: PublicationFieldInput[];
    },
  ) =>
    client.post<PublicationRevisionResponse>("/publications/revisions", {
      body: {
        slug: input.slug,
        pipeline_revision_id: input.pipelineRevisionId,
        title: input.title,
        ...(input.description ? { description: input.description } : {}),
        fields: input.fields,
      },
    }),

  /**
   * Open a revision to the catalog.
   *
   * Separate from creating it, so an admin can look at the form a revision
   * produces before researchers see it.
   */
  publish: (client: ApiClient, publicationId: string, revisionId: string) =>
    client.post<PublicationSummary>(`/publications/${publicationId}/publish`, {
      query: { revision_id: revisionId },
    }),

  archive: (client: ApiClient, publicationId: string) =>
    client.post<PublicationSummary>(`/publications/${publicationId}/archive`),
};

// --- the catalog ----------------------------------------------------------

export const catalogApi = {
  list: (client: ApiClient, search?: string) =>
    client.get<Page<CatalogSummary>>("/catalog", { query: { search } }),

  get: (client: ApiClient, slug: string) => client.get<CatalogDetail>(`/catalog/${slug}`),

  /**
   * Start a run from a catalog entry.
   *
   * The values are keyed by the publication's field keys — what the form
   * showed — not by anything inside the pipeline. The translation happens on
   * the server, where the bindings live.
   */
  submit: (
    client: ApiClient,
    slug: string,
    values: Record<string, unknown>,
    idempotencyKey: string,
  ) =>
    client.post<SubmitRunResponse>(`/catalog/${slug}/runs`, {
      body: { values },
      headers: { "Idempotency-Key": idempotencyKey },
    }),
};

// --- artifacts ------------------------------------------------------------

export const artifacts = {
  /** What it is, and — for a tree of results — what is in it. */
  get: (client: ApiClient, artifactId: string) =>
    client.get<ArtifactDetail>(`/artifacts/${artifactId}`),

  /**
   * Where the bytes are.
   *
   * A URL rather than a fetch: see `ApiClient.hrefFor`. Nothing in this app
   * ever holds an artifact in memory.
   */
  downloadHref: (client: ApiClient, artifactId: string) =>
    client.hrefFor(`/artifacts/${artifactId}/download`),

  fileHref: (client: ApiClient, artifactId: string, path: string) =>
    client.hrefFor(
      `/artifacts/${artifactId}/files/${path.split("/").map(encodeURIComponent).join("/")}`,
    ),
};

// --- runtime environments --------------------------------------------------

export const environments = {
  list: (client: ApiClient) => client.get<Page<EnvironmentSummary>>("/environments"),

  get: (client: ApiClient, environmentId: string) =>
    client.get<EnvironmentDetail>(`/environments/${environmentId}`),

  create: (
    client: ApiClient,
    input: { name: string; description?: string; makeDefault?: boolean },
  ) =>
    client.post<EnvironmentDetail>("/environments", {
      body: {
        name: input.name,
        description: input.description ?? null,
        make_default: input.makeDefault ?? false,
      },
    }),

  /**
   * Install, upgrade or uninstall.
   *
   * Slow by nature — a wheel that compiles takes minutes — and synchronous by
   * decision, so the caller waits. The operation row is written before the
   * build starts, so a request that gives up still leaves a record.
   */
  change: (
    client: ApiClient,
    environmentId: string,
    input: { operation: "install" | "upgrade" | "uninstall"; specifier: string },
  ) =>
    client.post<PackageOperation>(`/environments/${environmentId}/packages`, {
      body: { operation: input.operation, specifier: input.specifier },
    }),

  operations: (client: ApiClient, environmentId: string) =>
    client.get<Page<PackageOperation>>(`/environments/${environmentId}/operations`),

  generations: (client: ApiClient, environmentId: string) =>
    client.get<Page<GenerationSummary>>(`/environments/${environmentId}/generations`),

  unlock: (client: ApiClient, environmentId: string) =>
    client.post<EnvironmentSummary>(`/environments/${environmentId}/unlock`),

  makeDefault: (client: ApiClient, environmentId: string) =>
    client.post<EnvironmentSummary>(`/environments/${environmentId}/default`),

  /** What an author can call: the installed modules, or one module's functions. */
  callables: (client: ApiClient, environmentId: string, module?: string) =>
    client.get<Introspection>(`/environments/${environmentId}/callables`, {
      query: { module },
    }),
};

// --- saved values ----------------------------------------------------------

export const savedValues = {
  /**
   * The caller's saved values.
   *
   * Given an entry and a field, each comes back marked with whether it still
   * fits *that field* — the value's schema was frozen when it was saved and
   * the field's when the entry was published, so they can disagree.
   */
  list: (
    client: ApiClient,
    options: { entry?: string; fieldKey?: string; typeKey?: string } = {},
  ) =>
    client.get<Page<SavedValue>>("/saved-values", {
      query: { entry: options.entry, field_key: options.fieldKey, type_key: options.typeKey },
    }),

  save: (
    client: ApiClient,
    entry: string,
    input: { fieldKey: string; name: string; value: unknown },
  ) =>
    client.post<SavedValue>("/saved-values", {
      query: { entry },
      body: { field_key: input.fieldKey, name: input.name, value: input.value },
    }),

  rename: (client: ApiClient, valueId: string, name: string) =>
    client.patch<SavedValue>(`/saved-values/${valueId}`, { body: { name } }),

  remove: (client: ApiClient, valueId: string) => client.del<void>(`/saved-values/${valueId}`),
};

// --- uploads ---------------------------------------------------------------

export const uploads = {
  create: (
    client: ApiClient,
    input: { filename: string; sizeBytes?: number; checksum?: string },
  ) =>
    client.post<Upload>("/uploads", {
      body: {
        filename: input.filename,
        declared_size_bytes: input.sizeBytes ?? null,
        checksum_sha256: input.checksum ?? null,
      },
    }),

  get: (client: ApiClient, uploadId: string) => client.get<Upload>(`/uploads/${uploadId}`),

  /**
   * Append one chunk at `offset`.
   *
   * The chunk is a `Blob` slice, which the browser streams from the file on
   * disk — nothing reads it into memory, here or in the API process.
   */
  append: (
    client: ApiClient,
    uploadId: string,
    chunk: Blob,
    options: { offset: number; total: number; signal?: AbortSignal },
  ) =>
    client.patch<Upload>(`/uploads/${uploadId}`, {
      raw: chunk,
      headers: {
        "Content-Range": `bytes ${options.offset}-${options.offset + chunk.size - 1}/${options.total}`,
      },
      ...(options.signal ? { signal: options.signal } : {}),
    }),

  complete: (client: ApiClient, uploadId: string) =>
    client.post<Upload>(`/uploads/${uploadId}/complete`),

  abort: (client: ApiClient, uploadId: string) => client.del<Upload>(`/uploads/${uploadId}`),
};

// --- shared storage roots (admin) -----------------------------------------

export interface NewStorageRoot {
  id: string;
  label: string;
  rootPath: string;
  attestationNote: string;
  readable: boolean;
  writable: boolean;
}

export const storageRoots = {
  list: (client: ApiClient) => client.get<Page<StorageRoot>>("/storage/roots"),

  register: (client: ApiClient, input: NewStorageRoot) =>
    client.post<StorageRoot>("/storage/roots", {
      body: {
        id: input.id,
        label: input.label,
        root_path: input.rootPath,
        attestation_note: input.attestationNote,
        readable: input.readable,
        writable: input.writable,
      },
    }),

  revoke: (client: ApiClient, rootId: string, reason: string) =>
    client.post<StorageRoot>(`/storage/roots/${rootId}/revoke`, { body: { reason } }),

  reinstate: (client: ApiClient, rootId: string, attestationNote: string) =>
    client.post<StorageRoot>(`/storage/roots/${rootId}/reinstate`, {
      body: { attestation_note: attestationNote },
    }),
};

// --- schedules ------------------------------------------------------------

export interface NewSchedule {
  slug: string;
  title: string;
  values: Record<string, unknown>;
  rrule?: string | null;
  intervalSeconds?: number | null;
  timezone: string;
  dstPolicy: DstPolicy;
  catchupPolicy: CatchupPolicy;
  overlapPolicy: OverlapPolicy;
  maxConcurrentRuns: number;
  startAt?: string | null;
  endAt?: string | null;
}

export const schedules = {
  list: (client: ApiClient) => client.get<Page<ScheduleSummary>>("/schedules"),

  get: (client: ApiClient, scheduleId: string) =>
    client.get<ScheduleDetail>(`/schedules/${scheduleId}`),

  /**
   * Create one against a catalog entry, by slug.
   *
   * The revision that entry currently points at is pinned server-side, so
   * re-publishing never silently changes what a schedule has been running.
   */
  create: (client: ApiClient, input: NewSchedule) =>
    client.post<ScheduleDetail>("/schedules", {
      body: {
        slug: input.slug,
        title: input.title,
        values: input.values,
        ...(input.rrule ? { rrule: input.rrule } : {}),
        ...(input.intervalSeconds ? { interval_seconds: input.intervalSeconds } : {}),
        timezone: input.timezone,
        dst_policy: input.dstPolicy,
        catchup_policy: input.catchupPolicy,
        overlap_policy: input.overlapPolicy,
        max_concurrent_runs: input.maxConcurrentRuns,
        ...(input.startAt ? { start_at: input.startAt } : {}),
        ...(input.endAt ? { end_at: input.endAt } : {}),
      },
    }),

  pause: (client: ApiClient, scheduleId: string) =>
    client.post<ScheduleSummary>(`/schedules/${scheduleId}/pause`),

  resume: (client: ApiClient, scheduleId: string) =>
    client.post<ScheduleSummary>(`/schedules/${scheduleId}/resume`),

  archive: (client: ApiClient, scheduleId: string) =>
    client.post<ScheduleSummary>(`/schedules/${scheduleId}/archive`),
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

  retryDelivery: (client: ApiClient, runId: string, deliveryId: string) =>
    client.post<DeliverySummary>(`/runs/${runId}/deliveries/${deliveryId}/retry`),

  attempts: (client: ApiClient, runId: string, taskId: string) =>
    client.get<Page<AttemptSummary>>(`/runs/${runId}/tasks/${taskId}/attempts`),

  /**
   * What a task printed — the tail of it.
   *
   * A running attempt is read from the workspace the container is writing
   * into, so a long task can be watched; a finished one comes from its
   * artifact, which is also where the whole log lives.
   */
  log: (client: ApiClient, runId: string, taskId: string, attempt?: number) =>
    client.get<TaskLog>(`/runs/${runId}/tasks/${taskId}/log`, {
      query: { attempt },
    }),

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
