# PostgreSQL Data Model

## Status

This document is the design rationale. **The implemented schema is the
authority**: 33 tables in
[`backend/app/infrastructure/db/models/`](../backend/app/infrastructure/db/models/),
with the base migration in `backend/alembic/versions/`.

Changes since the original version, per
[15-premise-correction.md](15-premise-correction.md):

| Change | Reason |
| --- | --- |
| `pipeline_definitions` + `workflow_*` collapsed into `pipelines`, `pipeline_revisions`, `pipeline_inputs`, `pipeline_outputs` | One authoring level (ADR 0026) |
| `runtime_environments` rebuilt around a mutable venv; `environment_snapshots` and `package_operations` added | Admins install as normal work (ADR 0028) |
| `run_tasks` gained `task_class`, `cpu_request_millicores`, `memory_request_bytes`, `wall_time_limit_seconds`, `exclusive` | Resource admission control (ADR 0029) |
| `runs.environment_snapshot_id` | Provenance without image pinning |
| `type_definition_heads` and version-pinned saved values **removed** | Real types have no versions; snapshot-on-publish instead |
| `legacy_import_map` **removed** | No migration (ADR 0018) |
| `outbox_events` **removed** | No consumer at this scale |
| Persistence rule 8 realised as `projects` + `project_members`, one default row | ADR 0009 |
| Enums as `text` + named CHECK, generated from `app.domain.enums` | ADR 0011 |

Constraint names are **short suffixes**: the naming convention prepends
`ck_<table>_`. Passing a full name once produced 38 double-prefixed,
hash-truncated names, and a test now guards against it.

Alembic autogenerate **does not emit `use_alter` foreign keys**. Two circular
FKs were silently absent from the database despite the models declaring them;
they are created by explicit statements in
`scripts/dev/append_base_migration_sql.py`, and a test asserts they exist.

## Persistence rules

1. PostgreSQL is the system of record.
2. Filesystem storage holds large artifacts only.
3. All executable revisions are immutable.
4. All state transitions are timestamped and attributable.
5. Essential query fields are normalized; full compiled specs may also be stored as JSONB.
6. Schema migrations use Alembic and are part of every release.
7. Use UUID primary keys unless there is a clear reason not to.
8. Keep tenant/project columns even if the first deployment is single-project.

## Core tables

### Identity

```text
users
  id uuid pk
  email citext unique
  display_name text
  password_hash text null
  auth_provider text
  external_subject text null
  role text check in ('admin', 'researcher')
  is_active boolean
  created_at timestamptz
  updated_at timestamptz

sessions
  id uuid pk
  user_id uuid fk users
  token_hash text unique
  expires_at timestamptz
  created_at timestamptz
  revoked_at timestamptz null
```

Optional later: split roles and permissions into separate tables.

### Pipeline registry

```text
pipeline_definitions
  id uuid pk
  slug text unique
  title text
  description text
  owner_id uuid fk users
  status text
  created_at timestamptz
  updated_at timestamptz

pipeline_revisions
  id uuid pk
  pipeline_id uuid fk pipeline_definitions
  version integer
  source_format text
  source_text text
  normalized_spec jsonb
  validation_status text
  validation_report jsonb
  created_by uuid fk users
  created_at timestamptz
  unique (pipeline_id, version)
```

### Workflow authoring

```text
pipelines
  id uuid pk
  slug text unique
  title text
  description text
  owner_id uuid fk users
  status text
  created_at timestamptz
  updated_at timestamptz

pipeline_revisions
  id uuid pk
  workflow_id uuid fk pipelines
  version integer
  source_format text
  source_text text
  compiled_spec jsonb
  input_schema jsonb
  output_schema jsonb
  graph_hash text
  validation_status text
  validation_report jsonb
  created_by uuid fk users
  created_at timestamptz
  unique (workflow_id, version)
```

Keep `compiled_spec` as immutable JSONB. Normalize selected data below for querying and integrity.

```text
pipeline_inputs
  id uuid pk
  pipeline_revision_id uuid fk pipeline_revisions
  key text
  type_ref text
  primitive_type text
  required boolean
  default_value jsonb
  constraints jsonb
  source_policy jsonb
  unique (pipeline_revision_id, key)

pipeline_outputs
  id uuid pk
  pipeline_revision_id uuid fk pipeline_revisions
  key text
  artifact_kind text
  visibility text
  retention_policy jsonb
  unique (pipeline_revision_id, key)
```

### Publication catalog

```text
publications
  id uuid pk
  slug text unique
  current_revision_id uuid null
  status text check in ('draft', 'published', 'archived')
  created_by uuid fk users
  created_at timestamptz
  updated_at timestamptz

publication_revisions
  id uuid pk
  publication_id uuid fk publications
  pipeline_revision_id uuid fk pipeline_revisions
  version integer
  title text
  description text
  display_metadata jsonb
  access_policy jsonb
  created_by uuid fk users
  created_at timestamptz
  unique (publication_id, version)

publication_fields
  id uuid pk
  publication_revision_id uuid fk publication_revisions
  workflow_input_id uuid null fk pipeline_inputs
  workflow_output_id uuid null fk pipeline_outputs
  key text
  label text
  help_text text
  field_type text
  type_ref text null
  required boolean
  order_index integer
  ui_group text null
  default_value jsonb
  fixed_value jsonb null
  constraints jsonb
  source_policy jsonb
  save_policy jsonb
  visibility text
  unique (publication_revision_id, key)
```

### Runs and tasks

```text
runs
  id uuid pk
  publication_revision_id uuid null fk publication_revisions
  pipeline_revision_id uuid fk pipeline_revisions
  requested_by uuid fk users
  requested_from text check in ('manual', 'schedule', 'api', 'admin')
  status text
  status_reason text null
  input_values jsonb
  compiled_run_spec jsonb
  workspace_id uuid null
  created_at timestamptz
  queued_at timestamptz
  started_at timestamptz null
  finished_at timestamptz null
  updated_at timestamptz

run_field_values
  id uuid pk
  run_id uuid fk runs
  field_key text
  value jsonb
  value_source text
  artifact_id uuid null
  created_at timestamptz

run_tasks
  id uuid pk
  run_id uuid fk runs
  stage_key text
  task_key text
  status text
  priority integer
  dependencies_satisfied boolean
  task_spec jsonb
  claimed_by text null
  claimed_at timestamptz null
  started_at timestamptz null
  finished_at timestamptz null
  retry_count integer
  max_retries integer
  next_retry_at timestamptz null
  unique (run_id, task_key)

run_task_dependencies
  task_id uuid fk run_tasks
  depends_on_task_id uuid fk run_tasks
  primary key (task_id, depends_on_task_id)

run_task_attempts
  id uuid pk
  task_id uuid fk run_tasks
  attempt_number integer
  worker_id text
  container_id text null
  image_ref text
  exit_code integer null
  status text
  log_artifact_id uuid null
  started_at timestamptz
  finished_at timestamptz null
  result jsonb
  unique (task_id, attempt_number)
```

### Artifacts and files

```text
artifacts
  id uuid pk
  run_id uuid null fk runs
  task_id uuid null fk run_tasks
  owner_id uuid null fk users
  kind text
  storage_backend text
  storage_key text
  filename text
  content_type text null
  size_bytes bigint
  checksum_sha256 text
  visibility text
  created_at timestamptz
  expires_at timestamptz null
  deleted_at timestamptz null

workspaces
  id uuid pk
  run_id uuid fk runs
  root_key text
  status text
  quota_bytes bigint
  created_at timestamptz
  expires_at timestamptz null
  deleted_at timestamptz null
```

### Scheduling

```text
schedules
  id uuid pk
  publication_revision_id uuid fk publication_revisions
  owner_id uuid fk users
  status text check in ('active', 'paused', 'archived')
  rrule text
  timezone text
  input_values jsonb
  next_fire_at timestamptz
  last_fire_at timestamptz null
  last_run_id uuid null fk runs
  created_at timestamptz
  updated_at timestamptz

schedule_events
  id uuid pk
  schedule_id uuid fk schedules
  event_type text
  run_id uuid null fk runs
  message text null
  created_at timestamptz
```

### Types and saved values

```text
type_definitions
  id uuid pk
  key text
  version integer
  schema jsonb
  source text
  status text
  created_by uuid fk users
  created_at timestamptz
  unique (key, version)

saved_values
  id uuid pk
  user_id uuid fk users
  type_key text
  type_version integer null
  name text
  value jsonb
  created_at timestamptz
  updated_at timestamptz
  unique (user_id, type_key, name)
```

### Runtime environments

```text
runtime_environments
  id uuid pk
  name text unique
  image_ref text
  python_version text null
  package_manifest jsonb
  status text
  created_at timestamptz
  updated_at timestamptz
```

### Audit and outbox

```text
audit_events
  id uuid pk
  actor_id uuid null fk users
  action text
  target_type text
  target_id uuid null
  ip_address inet null
  user_agent text null
  metadata jsonb
  created_at timestamptz

outbox_events
  id uuid pk
  event_type text
  aggregate_type text
  aggregate_id uuid
  payload jsonb
  status text
  created_at timestamptz
  processed_at timestamptz null
```

## Migration practices

Use Alembic from the first commit. Every migration should include:

- Upgrade and downgrade when practical.
- Constraint names.
- Indexes for common list pages and worker queries.
- A test that a fresh database can migrate to head.
- A test that core seed data can be inserted.

## Query indexes to plan early

- `runs (requested_by, created_at desc)` for My Runs.
- `runs (status, updated_at)` for admin run dashboards.
- `run_tasks (status, priority, created_at)` for workers.
- `run_tasks (run_id, status)` for run summaries.
- `schedules (status, next_fire_at)` for scheduler claiming.
- `publication_fields (publication_revision_id, order_index)` for catalog rendering.
- `artifacts (run_id, kind, created_at)` for result pages.
- `audit_events (target_type, target_id, created_at desc)`.

## What should not be JSONB-only

Do not hide these inside JSONB only:

- Run status.
- Task status.
- Publication status.
- Current publication revision.
- Ownership and created_by values.
- Schedule next fire time.
- Artifact storage key and checksum.
- Field order and required flag.

JSONB is appropriate for compiled specs, validation reports, constraints, display metadata, package manifests, and submitted values after they are also linked to the relevant run or field.


## Review corrections and missing tables

> Findings below are registered with evidence, severity, and status in
> [gaps.md](gaps.md). This section says what to do about them.

The schema above is sound in shape but incomplete or self-contradictory in the
following places. These are corrections, not options.

### 1. Projects are required or rule 8 must go

Persistence rule 8 says "keep tenant/project columns even if the first
deployment is single-project", but no `projects` table exists and no table
carries a `project_id`. Either add the table and scope every owned entity, or
delete rule 8. Half-applied tenancy is the worst outcome.

```text
projects
  id uuid pk
  slug text unique
  title text
  status text
  created_at timestamptz

project_members
  project_id uuid fk projects
  user_id uuid fk users
  role text check in ('owner', 'admin', 'member', 'viewer')
  primary key (project_id, user_id)
```

If projects are adopted, `pipeline_definitions`, `pipelines`,
`publications`, `runs`, `artifacts`, `schedules`, `type_definitions`, and
`saved_values` all need `project_id` and every list query needs it in the filter
and in the index.

### 2. Worker registry and leases

Document 06 promises "a small heartbeat table can track live workers" and
"stale claims are detected by timeout". Neither exists here, and without them a
worker that dies mid-task strands the task in `claimed` forever.

```text
workers
  id text pk                     -- stable worker identity, e.g. host+pid+boot id
  hostname text
  version text
  runtime_environment_id uuid null fk runtime_environments
  capacity integer
  status text check in ('starting', 'active', 'draining', 'stopped')
  started_at timestamptz
  last_heartbeat_at timestamptz
```

And on `run_tasks`, claiming must be a lease, not a flag:

```text
run_tasks (additions)
  lease_expires_at timestamptz null   -- worker must renew or lose the task
  heartbeat_at timestamptz null
  cancel_requested_at timestamptz null
  attempt_count integer not null default 0
```

A task is reclaimable when `status = 'claimed' or 'running'` and
`lease_expires_at < now()`. Index it: `run_tasks (status, lease_expires_at)`.

### 3. Schedule firing must be idempotent at the row level

Document 06 requires "one run per due event" and document 09's acceptance
criterion is "once and only once", but `schedules` has no key that makes a
duplicate fire impossible. Locking alone does not survive a scheduler restart at
the wrong moment.

```text
schedule_fires
  id uuid pk
  schedule_id uuid fk schedules
  fire_at timestamptz            -- the scheduled window, not the actual time
  run_id uuid null fk runs
  outcome text check in ('created', 'skipped_overlap', 'skipped_catchup', 'failed')
  created_at timestamptz
  unique (schedule_id, fire_at)
```

The unique constraint is the guarantee. `schedule_events` remains for
human-readable history.

`schedules` also needs the policy columns that document 06's behavior implies but
which are not present:

```text
schedules (additions)
  catchup_policy text check in ('skip_missed', 'run_once', 'run_all')
  overlap_policy text check in ('skip', 'queue', 'allow')
  max_concurrent_runs integer
  end_at timestamptz null
  dst_policy text                -- how to resolve ambiguous or skipped local times
```

### 4. Run submission must be idempotent

Nothing prevents a double-submitted form from creating two runs.

```text
runs (additions)
  idempotency_key text null
  priority integer not null default 0
  cancel_requested_at timestamptz null
  cancel_requested_by uuid null fk users
  unique (requested_by, idempotency_key)   -- where idempotency_key is not null
```

### 5. Run and workspace relationship is circular

`runs.workspace_id uuid null` and `workspaces.run_id uuid fk runs` both exist,
with no FK on the former and no uniqueness on the latter. Keep one direction.
Recommendation: drop `runs.workspace_id`, and add `unique (run_id)` to
`workspaces` if a run has at most one workspace, or keep it non-unique and add
`task_id` if workspaces are per task. Document 06 says "a workspace is a
temporary execution layout for one run **or task**" - decide which.

### 6. Missing constraints

- `publication_fields`: exactly one of `workflow_input_id` and
  `workflow_output_id` must be set.
  `check (num_nonnulls(workflow_input_id, workflow_output_id) = 1)`.
- `publication_fields`: `fixed_value is null or visibility = 'hidden'` - a fixed
  value the researcher can also edit is a contradiction.
- `publications.current_revision_id` needs an FK to `publication_revisions` and a
  check that the revision belongs to this publication (enforce in a trigger or in
  the application service, and document which).
- `artifacts`: `unique (storage_backend, storage_key)` - two rows pointing at the
  same bytes with different lifecycles will cause the janitor to delete data that
  another row still claims.
- `artifacts`: add `task_attempt_id uuid null fk run_task_attempts`. A retry
  produces a second set of outputs; attributing them only to the task loses which
  attempt produced which bytes.
- `artifacts`: add `retention_class text` so the janitor has policy input other
  than a bare `expires_at`.
- `run_task_dependencies` needs a cycle guard. The compiler should reject cycles,
  but a defensive check at run materialisation is cheap.
- `sessions`: add `last_seen_at timestamptz` - the current system does sliding
  renewal and this schema cannot express it.

### 7. Output delivery policy is missing entirely

The current system supports output fields with `delivery: ["download"]` and
`delivery: ["shared"]`, where the reaper copies results into an allowlisted
shared root. Nothing in this schema can represent that. Add:

```text
pipeline_outputs (additions)
  delivery_modes jsonb          -- e.g. ["download", "shared"]

publication_fields (additions)
  delivery_policy jsonb         -- allowed modes, default mode, allowed shared roots

run_deliveries
  id uuid pk
  run_id uuid fk runs
  field_key text
  mode text check in ('download', 'shared')
  artifact_id uuid null fk artifacts
  target_root_id text null
  target_path text null
  status text check in ('pending', 'delivered', 'failed', 'skipped')
  attempts integer not null default 0
  message text null
  delivered_at timestamptz null
  unique (run_id, field_key, mode)
```

Delivery is a side effect that can fail independently of the run succeeding, so
it needs its own row and its own retry, not a boolean on the run.

### 8. Chunked upload state is missing

The current system already supports offset-append resumable uploads. A single
`artifacts` row cannot represent an upload in progress.

```text
uploads
  id uuid pk
  owner_id uuid fk users
  filename text
  declared_size_bytes bigint null
  received_bytes bigint not null default 0
  storage_key text
  checksum_sha256 text null
  status text check in ('open', 'completed', 'aborted', 'expired')
  created_at timestamptz
  completed_at timestamptz null
  expires_at timestamptz
  artifact_id uuid null fk artifacts
```

Abandoned open uploads are janitor work too.

### 9. Type version resolution is ambiguous

`type_definitions` has `unique (key, version)` but nothing marks the current
version, while `saved_values.type_version` is nullable. A null version has no
defined resolution rule. Either make the column non-null and resolve at write
time, or add `type_definition_heads (key, current_version)`. State the rule for
what happens to a saved value when its type gains a new version.

### 10. Read auditing

`audit_events` covers mutations. Document 06's audit list does not include
artifact **download**. For any regulated dataset, reads must be recorded. Either
log downloads as audit events or add a dedicated, cheaply-partitioned
`artifact_access_events` table - downloads are far more frequent than admin
actions and will dominate the audit table otherwise.

### 11. Outbox has no consumer

`outbox_events` exists, but the process list in document 02 has no relay. Either
name the process that drains it (`worker`, `janitor`, or a dedicated `relay`) or
remove the table until a use case exists. An unread outbox is a table that only
grows.

### 12. Secrets

If a task needs credentials to reach an external database or an institutional
service, there is nowhere to put them. Either state that tasks never need secrets
(and enforce it in the execution adapter's environment scrubbing) or add a
secret reference model with values held outside Postgres.

## Additional indexes

Add to the list above:

- `run_tasks (status, lease_expires_at)` for stale-claim reaping.
- `run_tasks (status, next_retry_at)` for retry pickup.
- `artifacts (expires_at) where deleted_at is null` for the janitor.
- `uploads (status, expires_at)` for abandoned-upload cleanup.
- `sessions (expires_at)` for session pruning.
- `outbox_events (status, created_at)` if the table is kept.
- `schedule_fires (schedule_id, fire_at desc)`.
- `run_deliveries (status, run_id)`.
- A trigram or full-text index for catalog search - document 07 specifies search
  and filtering over the catalog, and nothing here supports it.

## Enum policy

The tables above mix `text check in (...)` with bare `text` for the same kind of
field. Choose one convention and apply it everywhere:

- **Recommended**: `text` plus a named check constraint, because adding a value is
  an ordinary migration and Postgres native enums cannot drop values.
- Whichever is chosen, the allowed values must be generated from one place shared
  with the Pydantic models, so the database and the API cannot disagree.

## Partitioning and growth

`run_tasks`, `run_task_attempts`, `artifacts`, `audit_events`, and any download
log are the tables that will grow without bound. Decide now whether they are
partitioned by month - retrofitting partitioning onto a large live table is
painful. This depends on the load numbers in
[11-non-functional-requirements.md](11-non-functional-requirements.md).
