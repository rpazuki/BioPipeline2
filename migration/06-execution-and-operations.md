# Execution and Operations

## Superseded sections

Three parts of the original document are void; see
[15-premise-correction.md](15-premise-correction.md):

- **Immutable pinned images.** Replaced by a mutable shared virtualenv with
  per-run snapshots (ADR 0028). Admins install packages as normal work.
- **Rootless Podman, SELinux volume labels, Red Hat specifics.** Docker on a
  generic Linux VM (ADR 0008).
- **Container hardening as a security boundary.** Code is admin-authored and
  trusted (ADR 0030). Containers give resource limits, timeouts and crash
  isolation. Researcher *input* remains untrusted, so path containment, input
  validation and SSRF controls on `url` inputs stay strict.

The current execution model lives in
[`docs/architecture/execution-model.md`](../docs/architecture/execution-model.md)
and covers admission control, leases, cancellation, upgrades and snapshots in
detail. This document keeps the operational material.

## Runtime processes

| Process | Responsibility |
| --- | --- |
| `api` | HTTP API, auth, validation, application services |
| `frontend` | Next.js UI |
| `worker` | Claims tasks under admission control, runs task containers |
| `scheduler` | Creates due scheduled runs |
| `janitor` | Retention, output packaging, workspace and snapshot cleanup, lease reclamation |
| `postgres` | System of record |
| `reverse-proxy` | TLS, path prefix |

No outbox relay: the table was dropped, since at this scale nothing needed it.

Scheduler leadership needs no election. Correctness comes from the
`(schedule_id, fire_at)` unique constraint on `schedule_fires`, so two
schedulers cannot double-fire a window; an advisory lock is optional noise
reduction only.

## Task execution model

Workers should not run scientific code in the API process. A task should execute inside an isolated container selected by the pipeline revision or runtime environment.

Task execution steps:

1. Worker claims a `run_tasks` row using a transaction and `FOR UPDATE SKIP LOCKED`.
2. Worker creates a task attempt row.
3. Worker materializes the task workspace from artifacts and prior task outputs.
4. Worker starts a container with a read/write mount for the task workspace.
5. Worker streams stdout/stderr to log storage.
6. Worker validates declared outputs after the container exits.
7. Worker records success or failure and creates artifact records.
8. Orchestrator marks dependent tasks ready when dependencies succeed.

## Container isolation

Minimum task container controls:

- Run as non-root where possible.
- Resource limits: CPU, memory, process count, wall-time timeout.
- Workspace mounted at a predictable path such as `/work`.
- No host filesystem access outside approved mounts.
- Configurable network policy. Default should be no outbound network for tasks unless explicitly allowed.
- Environment variables explicitly listed and scrubbed of secrets.
- Volume mount flags appropriate to the host; no SELinux labelling is
  required on a generic Linux VM.

Docker is the supported runtime (ADR 0008). The execution adapter stays behind an interface so Podman remains reachable if the institution later requires it.

## Queue and locking

Initial design can use PostgreSQL:

- Workers claim queued tasks with `FOR UPDATE SKIP LOCKED`.
- Scheduler claims due schedules similarly.
- A small heartbeat table can track live workers.
- Stale claims are detected by timeout and requeued according to retry policy.

This keeps the first deployment simple. Add Redis, Celery, or another broker only after measured need.

## Artifacts and storage

Storage should be accessed through an artifact service abstraction.

Initial backend:

- POSIX directory mounted into API and workers.
- Directory layout rooted by environment and object id, not user-supplied filenames.
- Checksums recorded for all artifacts.
- Generated downloads served through authenticated API endpoints.

Future backend:

- S3-compatible object storage such as MinIO.
- Signed URLs for large downloads if policy allows.

Recommended artifact kinds:

- `upload_input`
- `shared_input_reference`
- `task_output`
- `run_output_package`
- `task_log`
- `manifest`
- `diagnostic`

## Workspaces

A workspace is an execution convenience, not the record of truth.

Rules:

- Workspace paths are generated, never user-chosen.
- Inputs copied or linked into the workspace are recorded as artifacts.
- Outputs are promoted to artifacts after task completion.
- Cleanup is driven by retention policy and artifact records.
- Packaging outputs should be idempotent.
- Rewind/retry should rebuild from artifacts, not rely on old mutable workspace state.

## Scheduling

Schedules should create normal runs. They should not have a separate execution path.

Scheduler behavior:

- Claim due schedules transactionally.
- Create one run per due event unless policy says to skip missed windows.
- Record schedule events for created, skipped, failed, and paused outcomes.
- Store timezone explicitly.
- Prevent overlapping runs per schedule unless explicitly allowed.

## Observability

Minimum production observability:

- Structured JSON logs with request id, user id when available, run id, task id, worker id.
- Health endpoints for API, worker, scheduler, database, storage, and runtime environment checks.
- Metrics for run counts, task counts, queue depth, task duration, failure rate, storage usage, scheduler lag.
- Audit events for login, publish, archive, submit run, cancel run, delete artifact, change user role, and runtime environment edits.

## Backups and restore

A VM deployment must have a tested backup story before production use.

Back up:

- PostgreSQL database.
- Artifact storage root.
- Deployment configuration.
- Runtime environment manifests.

Restore test:

1. Start a clean VM or clean compose project.
2. Restore Postgres.
3. Restore artifacts.
4. Start services.
5. Verify users, publications, runs, and downloads.
6. Execute a small test workflow.

## Linux VM deployment

Recommended initial production layout:

```text
/opt/biopipeline2/
  compose.yaml
  .env
  nginx/
  postgres/
  artifacts/
  backups/
  logs/
```

Operational recommendations:

- Use Docker where possible.
- Manage containers with systemd units.
- Configure volume mounts and their ownership for the service account.
- Keep secrets in an env file readable only by the service account or use the institution's secret manager.
- Terminate TLS at Nginx, Caddy, Apache, or the institutional gateway.
- Support a path prefix such as `/biopipeline` from the beginning.
- Document firewall ports and required outbound access.

## Security baseline

- Authenticate all non-health endpoints.
- Enforce backend authorization even if UI hides controls.
- Validate all paths with containment checks.
- Never trust filenames from uploads.
- Scan or at least quarantine uploads if institutional policy requires it.
- Log admin actions.
- Store passwords with Argon2id or institution-approved hashing.
- Protect session cookies with `HttpOnly`, `Secure`, and `SameSite` appropriate to deployment.
- Separate admin and researcher APIs by authorization policy, not by frontend routing alone.

## Operational runbooks to write

- Install on Linux VM.
- Upgrade release.
- Roll back release.
- Backup and restore.
- Rotate secrets.
- Recover stuck tasks.
- Recover failed scheduler.
- Inspect task logs.
- Clean storage safely.
- Add or update runtime environment image.


## Review additions

> Findings below are registered with evidence, severity, and status in
> [gaps.md](gaps.md). This section says what to do about them.

The execution model is the right shape. The mechanisms below are named as
requirements elsewhere in the plan but never specified, and each one is a way the
system can lose or strand work.

### Task leases, not claims

"Stale claims are detected by timeout and requeued" needs a concrete protocol,
because this is the single most common source of stuck work:

1. Claiming sets `lease_expires_at = now() + lease_ttl`.
2. The worker renews the lease on a heartbeat interval well below `lease_ttl`.
3. A reaper (the janitor, or the scheduler) requeues tasks whose lease has
   expired, incrementing `attempt_count`.
4. `lease_ttl` must exceed the longest expected pause in the worker loop but not
   the p95 task duration - so it is renewed during execution, never sized to
   cover it.
5. A poison-task limit: after N lease expiries without a clean outcome, mark the
   task `failed` with a distinct reason rather than looping forever.
6. Reclaiming a task must handle the orphaned container: the reaper cannot assume
   the old container is gone. Record `container_id` on the attempt and reconcile
   by label on worker start.

Requires the `workers` table and the `run_tasks` lease columns added in
[04-data-model-postgres.md](04-data-model-postgres.md).

### Cancellation mechanism

The task execution steps above do not mention cancellation at all, yet `cancel`
is an API endpoint and `cancel_requested` is a run status. Specify:

- The worker polls `cancel_requested_at` on its own tasks on the heartbeat
  interval, or receives a `NOTIFY`.
- On cancel: send SIGTERM to the container, wait a stated grace period, then
  SIGKILL. Record which happened.
- Queued tasks are cancelled by row update without ever starting.
- Partial outputs: state whether they are kept as artifacts, kept but marked
  incomplete, or discarded. Researchers will ask.
- A run in `cancel_requested` with no live worker must still converge to
  `cancelled` - the reaper owns that transition.

### Orphan and drift reconciliation

On worker start, and periodically:

- List containers with this platform's label. Any container whose task row is not
  `running` on this worker is an orphan - stop it and record it.
- Any task row `running` on this worker with no container is a lost task - fail
  the attempt.
- Report both as metrics; a nonzero steady-state count means a bug.

### Task entry-point contract

The plan says scientific code runs in containers and that science packages stay
external, but never says how a workflow names a callable. This blocks the Phase 2
compiler. Specify at least:

- How a task is invoked: a fixed command in the image, or a launcher the platform
  injects.
- How parameters arrive: a JSON file at a known path is the obvious choice, and
  matches the current `TASK.json` subprocess convention.
- How outputs are declared and discovered: the task writes to declared paths and
  emits a machine-readable result document; the worker validates against the
  compiled output declarations.
- How failures are distinguished: exit code plus an optional structured error
  document, so a validation failure reads differently from a crash.
- What the container may assume: workspace at `/work`, no network by default,
  which environment variables are guaranteed.

Write this as a versioned contract document under `docs/architecture/`, because
task images depend on it and it cannot change silently.

### Runtime environment images

Replacing UI-driven package installs with immutable images removes an admin
capability (see row 12 of
[10-feature-parity-and-scope.md](10-feature-parity-and-scope.md)). The
replacement workflow must exist, or admins will be blocked:

- Where an image definition lives (in the repository, or as an uploaded
  specification), and who can edit it.
- How it is built - and where, given a production VM that may have no outbound
  internet. An internal registry and a package mirror are likely prerequisites.
- Pinning: image digest, not tag. `runtime_environments.image_ref` should record
  the digest actually used by a run, or provenance is lost.
- Promotion and rollback: how a new image becomes the default, and how to revert.
- Introspection: the current system lets admins list and search installed
  functions and read signatures. That must still work against an image, or the
  authoring UX loses its discovery mechanism.
- Vulnerability scanning and a base-image update cadence.

### Resource governance

Container CPU and memory limits are mentioned; system-level governance is not.
Add:

- Maximum concurrent tasks per worker and globally.
- Maximum concurrent runs per user, and behaviour on breach (reject or `blocked`).
- Per-user storage quota alongside the per-run workspace quota.
- A fair-share or weighted policy so one large fan-out cannot starve other users.
  The `priority` column is a mechanism, not a policy - state the policy.
- Task classes if some work needs large memory or a GPU.

### Deployment interaction with long-running tasks

Document 06's upgrade story and long-running scientific tasks conflict. State:

- Workers support draining: stop claiming, finish or cancel in-flight tasks.
- The maximum drain time before an upgrade proceeds anyway.
- Whether a task killed by an upgrade is retried automatically.
- Whether a schema migration can run while tasks are in flight. With the
  expand/contract rule in
  [12-testing-ci-and-release.md](12-testing-ci-and-release.md), it can - without
  it, it cannot.

### Scheduler leadership

"Exactly one active leader at a time" is an assertion, not a mechanism. Use an
advisory lock in Postgres (`pg_try_advisory_lock`) held for the lifetime of the
leader, or accept multiple schedulers and rely on the
`schedule_fires (schedule_id, fire_at)` unique constraint for correctness. The
second option is more robust and needs no leader election - prefer it, and keep
the lock only as a noise reduction.

Also missing: timezone and DST handling. An RRULE in a local timezone has
ambiguous and non-existent local times twice a year. State the resolution rule.

### Observability additions

- **Distributed tracing** (OpenTelemetry) across API, worker, and container
  launch. With four processes and a database queue, correlating a slow submit
  without traces is guesswork. Propagate a run id and trace id into the task
  environment.
- **Log retention and content policy**: how long task logs are kept, and the rule
  against logging input values that may contain sensitive data.
- **Alerting thresholds**, not just metrics: queue depth, oldest queued task age,
  lease-expiry rate, delivery failure rate, disk headroom, scheduler lag,
  restore-rehearsal failure.
- **A "system stuck" signal**: oldest `queued` task age is the single most useful
  alert this architecture has.

### Backup additions

Document the RPO and RTO targets (see
[11-non-functional-requirements.md](11-non-functional-requirements.md)) - the
restore test has no pass condition without them. Add:

- Point-in-time recovery via WAL archiving, or an explicit acceptance that
  recovery is to the last nightly dump.
- Backup encryption and where the keys live.
- Consistency between the database and the artifact volume: an artifact row
  restored without its bytes, or bytes without a row, must be detectable. Add a
  reconciliation script and run it after every restore rehearsal.
- Backup **monitoring**: an unnoticed failing backup is the normal failure mode.
- A restore rehearsal on a schedule, not once at go-live.

### Security additions

- Enforce path containment and shared-root allowlists in one shared module used
  by the API, the worker, and the janitor - the current system's containment
  idiom is worth carrying deliberately rather than reimplementing per call site.
- If `url` inputs are carried, apply the SSRF controls in document 05, and prefer
  fetching from a worker with no privileged network access.
- Decide whether the platform accesses shared storage as the requesting user or
  as a service account. As a service account it bypasses institutional POSIX
  permissions - that is a governance decision, not an implementation detail.
- Scrub the task environment to an allowlist, and assert in a test that no
  platform secret (database URL, session key, provider API key) is visible inside
  a task container.
- Container escape posture: no privileged containers, no docker socket mounted
  into any task, `--read-only` root filesystem with explicit writable mounts,
  dropped capabilities, and `no-new-privileges`.
- Uploaded archive handling: reject or safely extract archives with absolute
  paths, `..` components, or symlinks pointing outside the workspace.
