# API and Contracts

## Contract principles

1. OpenAPI is the source for frontend API types.
2. Route handlers are thin adapters around application services.
3. Use resource names that match the domain model.
4. Public catalog endpoints should not expose admin-only implementation details.
5. Every mutating request should produce an audit event.
6. Errors should have a stable shape and machine-readable codes.
7. Long-running state is observed through run, task, log, and event endpoints, not ad hoc polling hacks.

## API versioning

Use `/api/v1` from the beginning. Additive changes can remain in the same version. Breaking response or behavior changes require a new version or a documented compatibility strategy.

## Error model

Standard error shape:

```json
{
  "error": {
    "code": "workflow.validation_failed",
    "message": "Workflow validation failed.",
    "details": {
      "errors": [
        {"path": "workflow.inputs.sample_sheet", "message": "Field is required."}
      ]
    },
    "request_id": "req_..."
  }
}
```

Use consistent HTTP status codes:

- `400`: malformed request or validation failure.
- `401`: not authenticated.
- `403`: authenticated but forbidden.
- `404`: resource not found or not visible.
- `409`: state conflict, duplicate slug, stale revision.
- `422`: semantically invalid domain input.
- `500`: unexpected server error.

## Router map

### Auth

```text
POST   /api/v1/auth/login
POST   /api/v1/auth/logout
GET    /api/v1/auth/session
POST   /api/v1/auth/change-password
```

Later SSO should be added behind the same session contract.

### Pipelines

```text
GET    /api/v1/pipelines                              built
POST   /api/v1/pipelines/revisions                    built
GET    /api/v1/pipelines/{pipeline_id}/revisions      built
GET    /api/v1/pipelines/revisions/{revision_id}      built
POST   /api/v1/pipelines/compile-preview              built
GET    /api/v1/pipelines/{pipeline_id}
PATCH  /api/v1/pipelines/{pipeline_id}
POST   /api/v1/pipelines/revisions/{revision_id}/validate
```

Revisions sit under `/pipelines/`, not at a sibling `/pipeline-revisions/`.
An earlier draft of this document specified both, and the code chose the
nested form: a revision has no meaning apart from its pipeline, and one prefix
is one thing to authorise, version and document. The two route shapes cannot
shadow each other — `/pipelines/{id}/revisions` ends in a literal segment and
`/pipelines/revisions/{id}` ends in an identifier — and a test asserts it.

`compile-preview` takes source text rather than a stored revision id, because
its whole purpose is to compile a document that is not stored yet. It returns
diagnostics, the input contract and the stage graph without creating a run.
A document that is structurally invalid comes back as diagnostics with a 200,
the same as one that is semantically invalid.

Both compile paths resolve components through the configured
`component_library_root` (ADR 0026). Preview and save must use the same loader,
or a preview would approve a document the save then rejects.

`GET /pipelines/revisions/{revision_id}` serves the input contract a
submission must satisfy, read from the revision's stored `input_schema` rather
than recompiled: a revision is immutable, so what it declares today has to be
what it declared when it was published.

### Publications and catalog

Admin publication endpoints:

```text
GET    /api/v1/publications
POST   /api/v1/publications
GET    /api/v1/publications/{publication_id}
PATCH  /api/v1/publications/{publication_id}
POST   /api/v1/publications/{publication_id}/revisions
POST   /api/v1/publications/{publication_id}/publish
POST   /api/v1/publications/{publication_id}/archive
GET    /api/v1/publication-revisions/{revision_id}
```

Researcher catalog endpoints:

```text
GET    /api/v1/catalog
GET    /api/v1/catalog/{publication_slug}
POST   /api/v1/catalog/{publication_slug}/runs
POST   /api/v1/catalog/{publication_slug}/drafts
```

The catalog detail response should include only the published field schema, allowed source modes, display metadata, and submission endpoint data.

### Runs and tasks

```text
GET    /api/v1/runs
GET    /api/v1/runs/{run_id}
POST   /api/v1/runs/{run_id}/cancel
POST   /api/v1/runs/{run_id}/retry
DELETE /api/v1/runs/{run_id}
GET    /api/v1/runs/{run_id}/tasks
GET    /api/v1/runs/{run_id}/artifacts
GET    /api/v1/tasks/{task_id}
GET    /api/v1/tasks/{task_id}/attempts
GET    /api/v1/tasks/{task_id}/logs
```

Use authorization filters so researchers only see their own runs unless policy says otherwise.

### Files and artifacts

```text
POST   /api/v1/files/uploads
GET    /api/v1/files/uploads/{upload_id}
DELETE /api/v1/files/uploads/{upload_id}
GET    /api/v1/artifacts/{artifact_id}
GET    /api/v1/artifacts/{artifact_id}/download
POST   /api/v1/shared-storage/browse
```

All shared-storage browsing must be rooted in configured allowlisted roots.

### Schedules

```text
GET    /api/v1/schedules
POST   /api/v1/schedules
GET    /api/v1/schedules/{schedule_id}
PATCH  /api/v1/schedules/{schedule_id}
POST   /api/v1/schedules/{schedule_id}/pause
POST   /api/v1/schedules/{schedule_id}/resume
POST   /api/v1/schedules/{schedule_id}/run-now
DELETE /api/v1/schedules/{schedule_id}
```

### Type library and saved values

```text
GET    /api/v1/types
POST   /api/v1/types
GET    /api/v1/types/{type_key}
POST   /api/v1/types/import/python
GET    /api/v1/saved-values
POST   /api/v1/saved-values
PATCH  /api/v1/saved-values/{saved_value_id}
DELETE /api/v1/saved-values/{saved_value_id}
```

### Runtime environments

```text
GET    /api/v1/runtime-environments
POST   /api/v1/runtime-environments
GET    /api/v1/runtime-environments/{environment_id}
POST   /api/v1/runtime-environments/{environment_id}/health-check
```

### Admin operations

```text
GET    /api/v1/admin/audit-events
GET    /api/v1/admin/system-health
GET    /api/v1/admin/storage-usage
POST   /api/v1/admin/backups
```

## Event streams

Use Server-Sent Events or WebSocket for live run updates.

Recommended first implementation:

```text
GET /api/v1/runs/{run_id}/events
```

Events:

- `run.status_changed`
- `task.status_changed`
- `task.log_appended`
- `artifact.created`
- `run.output_packaged`
- `run.expired`

The event stream is a convenience. The database remains authoritative, and the UI must recover by refetching run detail.

## Generated clients

The frontend should not hand-maintain a large fetch wrapper. Generate TypeScript types and request functions from OpenAPI, then wrap them in feature-level hooks.

Suggested frontend pattern:

```text
frontend/src/generated/api-client.ts
frontend/src/features/runs/api.ts
frontend/src/features/runs/hooks.ts
frontend/src/features/runs/components/RunStatusBadge.tsx
```

## Authorization policy

Initial roles:

- Admin: manages pipeline revisions, pipeline revisions, publications, users, runtime environments, and all runs.
- Researcher: views catalog, submits runs, manages own schedules, views own saved values and runs.

Add permissions later if institutions need finer control. Avoid hard-coding role checks deep in UI components. Backend authorization is authoritative.

## Compatibility strategy

If the first release must preserve user-facing terms, expose labels such as "Published Jobs" in the UI while keeping API resources named `publications`, `runs`, and `tasks`. Do not carry old internal names into new contracts.


## Review additions

> Findings below are registered with evidence, severity, and status in
> [gaps.md](gaps.md). This section says what to do about them.

The router map above is a good skeleton but is missing the conventions that make
a REST API usable and safe. These are not optional details; each one is either a
correctness problem or a regression against the current system.

### List conventions

No document specifies pagination, sorting, or filtering, yet document 07 assumes
list pages with "query keys by feature, filters, page, and sort". Decide once and
apply to every collection endpoint:

- **Pagination**: cursor-based (`?limit=&cursor=`) for anything that grows without
  bound (`runs`, `run_tasks`, `artifacts`, `audit_events`); offset pagination is
  acceptable for small admin lists but must not be the default.
- **Envelope**: one shape for every list response, e.g.
  `{"items": [...], "next_cursor": "...", "total": null}`. `total` may be null
  where counting is expensive - say so rather than making the frontend guess.
- **Sorting**: an explicit allowlist of sortable fields per resource.
- **Filtering**: named query parameters, not a generic query language.

### Idempotency

`POST /catalog/{slug}/runs` must accept an `Idempotency-Key` header and return
the existing run on a repeat. Without it, a double-clicked submit button or a
retried request creates duplicate runs - and for a run that occupies a shared
compute node, that is expensive rather than merely untidy. The same applies to
`POST /runs/{id}/retry` and `POST /schedules/{id}/run-now`.

### Optimistic concurrency

The error model already reserves `409` for "stale revision", but nothing carries
a version. Use `ETag` on `GET` and require `If-Match` on `PATCH` for resources
two admins can edit simultaneously: publications, publication revisions in draft,
workflow templates, schedules.

### Uploads: chunked and resumable

The current system supports offset-append resumable uploads. `POST /files/uploads`
as a single request is a regression, and for multi-gigabyte inputs it is not
workable. Specify:

```text
POST   /api/v1/uploads                      -> create an upload, returns id and chunk policy
PATCH  /api/v1/uploads/{upload_id}          -> append bytes at an offset (Content-Range)
GET    /api/v1/uploads/{upload_id}          -> received_bytes, status, checksum
POST   /api/v1/uploads/{upload_id}/complete -> finalise, verify checksum, mint an artifact
DELETE /api/v1/uploads/{upload_id}          -> abort
```

**Built, and stated** — [ADR 0033](docs/adr/0033-upload-transport-and-the-large-input-path.md)
answers each of the questions this section asked for:

| | |
| --- | --- |
| Maximum chunk | `upload_chunk_max_bytes`, 64 MB by default; the browser slices at 8 MB whatever the ceiling is |
| Maximum total | `upload_max_total_bytes`, 500 GB by default, refused at creation when a size is declared |
| Checksum | SHA-256, optional from the client; always computed by the server over what arrived |
| Expiry | `upload_expiry_hours`, 48 by default, measured from the **last chunk** rather than from creation |
| Unexpected offset | `409 upload.offset_conflict`, carrying `expected_offset`; never silently accepted |

The direct-to-storage path this section asks for, on the single VM of ADR 0008,
is the **shared root**: a file in the tens of gigabytes is put there with the
tools built for moving data at that size and named in the form, rather than
pushed through the API process that also answers every other request. HTTP
upload is the small-file case, as predicted here.

### Downloads

- Support HTTP range requests on `GET /artifacts/{id}/download`; a researcher
  resuming a 40 GB download over a campus VPN is the normal case, not the edge.
- State whether downloads are audited (see the read-auditing item in document 04).
- If `run_output_package` zipping becomes optional for large outputs, add a
  manifest endpoint so the UI can offer per-file download.

### Input source modes, including `url`

Document 03's `source_modes: [upload, shared]` omits the `url` mode the current
system supports, where the server fetches a researcher-supplied URL. If it is
carried, the contract must state the controls, because server-side fetch is an
SSRF primitive:

- Allowed schemes (`https` only, realistically).
- A host allowlist, or an explicit denylist of link-local, loopback, and private
  ranges, applied **after** DNS resolution and re-applied on every redirect.
- Redirect limit, connect and read timeouts, maximum bytes with the connection
  dropped on breach.
- Whether the fetch happens in the API process or is delegated to a worker with
  no privileged network access. Prefer the worker.

### Output delivery

The current system lets a published output field be delivered by download and/or
copied into an allowlisted shared root. Nothing in the router map exposes this.
Add delivery state to the run response and:

```text
GET    /api/v1/runs/{run_id}/deliveries
POST   /api/v1/runs/{run_id}/deliveries/{delivery_id}/retry
```

Delivery can fail after a run succeeds, so the UI needs to see it as its own
state rather than inferring it.

**Built.** Both endpoints exist, and a delivery row carries `target_path` — the
path it actually landed at, which is the question a researcher asks next and
which they cannot work out from the root alone. The copying is done by a
process of its own (`app/workers/courier.py`) rather than by a worker or the
reaper, because a delivery is a copy of arbitrarily many gigabytes and both of
those have to stay responsive while it runs. Three rules that are not
negotiable: copy rather than link, write through a temporary name and rename,
and never overwrite anything already on the share.

### Cancellation semantics

`POST /runs/{run_id}/cancel` returns immediately, but the run has running
containers. The contract must state: the response is an acknowledgement, the run
moves to `cancel_requested`, tasks stop within a stated grace period, and the
client observes `cancelled` via the run resource or the event stream. Also state
what happens to partial outputs.

### Authentication hardening

Document 06's security baseline covers cookies and hashing but the API contract
is missing three things that matter for a cookie-authenticated app:

- **CSRF.** Cookie auth plus state-changing `POST`/`PATCH`/`DELETE` requires
  either `SameSite=Strict`/`Lax` with a documented cross-origin story, or a
  double-submit token, or a custom-header requirement enforced server-side.
  Document 07 puts the frontend on a separate origin in development, which is
  exactly the case that breaks naive assumptions. Decide and write it down.
- **Rate limiting and lockout** on `POST /auth/login` and
  `POST /auth/change-password`, with the lockout policy stated (threshold,
  window, unlock path) so it is not invented per-deployment.
- **Session invalidation** on password change and on role change, and whether an
  admin can revoke another user's sessions.

Also missing from the auth surface: password reset (the plan has
`change-password` but no forgotten-password path), and initial admin bootstrap -
the current system does this through the CLI, which document 10 flags as an
undecided deliverable.

### Health and readiness

Document 06 requires health endpoints; the router map has only
`/admin/system-health`, which is admin-authenticated. Add unauthenticated
`GET /health` (liveness) and `GET /ready` (dependency checks) so a reverse proxy
and container runtime can use them, and keep the detailed authenticated variant
for operators.

### Worker-facing API

Document 06 has workers claiming rows directly in Postgres. That is a legitimate
choice, but it means workers hold database credentials and depend on the schema.
State it as a decision and record the consequence: worker and API must be
deployed as a matched pair, because a schema change breaks both. If workers are
ever to run on hosts outside the database's trust boundary, an HTTP claim API is
needed instead - decide now, because it is a hard change later.

### Contract governance

- Commit `contracts/openapi.json` and fail CI on an undeclared diff.
- Define what counts as a breaking change (removing a field, narrowing a type,
  adding a required request field, changing an error code) and require a label or
  an ADR for one.
- If the MCP server or a CLI survives, they are contract consumers and must be in
  the same CI gate - see [12-testing-ci-and-release.md](12-testing-ci-and-release.md).

### Event stream details

The event list is good. Missing operational detail: authentication of the SSE
connection, per-user connection limits, replay via a `Last-Event-ID` cursor, a
heartbeat/keep-alive so proxies do not drop idle streams, and the maximum log
line rate before `task.log_appended` is coalesced or truncated. Also add
`run.delivery_changed` once output delivery exists.
