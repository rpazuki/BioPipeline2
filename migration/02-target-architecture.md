# Target Architecture

## Corrections

Per [15-premise-correction.md](15-premise-correction.md), this is a **generic
Python execution and orchestration platform**, not a bioinformatics data
system. It holds no data corpus.

Changes to the bounded-context table and process layout:

- **Pipeline Registry and Workflow Authoring merge.** One authoring level
  (ADR 0026): `Pipeline` owns definitions, revisions, compilation and
  validation.
- **Runtime Environments is promoted from a peripheral context to a core one.**
  In a platform that executes arbitrary Python, "what can I call?" is the
  authoring experience. It owns the mutable shared virtualenv, per-run
  snapshots, install history and callable introspection.
- **No outbox relay process.** The table was dropped.
- **Notifications** is a real context if ADR 0014 is accepted, which day-long
  tasks argue for. The "email" adapter listed under infrastructure is otherwise
  unused and should be removed.
- **AI Assistance** stays absent pending ADR 0002.

Non-browser consumers of the domain layer — a CLI, a notebook client, the
74-tool MCP server — remain undecided (ADR 0003, ADR 0004). The rule stands
regardless: an in-process CLI is a thin adapter over the application layer, and
any out-of-process consumer is an OpenAPI consumer that must be generated or
contract-tested. An admin bootstrap path that does not need a running frontend
is required either way, because something must create the first user.

## Architectural principles

1. Every executable thing is versioned.
2. Authoring formats are not runtime state.
3. The public researcher contract is explicit and stable.
4. The database is the system of record; files are artifacts.
5. API, worker, scheduler, and cleanup are separate processes.
6. Scientific code runs in isolated task containers.
7. Documentation is a product surface, not a side note.
8. Local VM deployment must be boring, repeatable, and recoverable.

## Bounded contexts

| Context | Owns | Does not own |
| --- | --- | --- |
| Identity and RBAC | Users, sessions, roles, permissions | Workflow execution rules |
| Pipeline Registry | Pipeline definitions, pipeline revisions, validation | Researcher-facing publication text |
| Workflow Authoring | Workflow templates, stages, dependencies, fan-out, compile errors | Task claiming or artifact cleanup |
| Schema and Fields | Type library, workflow input contracts, saved values | YAML path mutation |
| Catalog and Publication | Published entries, publication revisions, researcher visibility | Low-level task specs |
| Run Orchestration | Runs, tasks, dependencies, task state transitions | Container implementation details |
| Execution | Task attempts, container launch, logs, exit status | Catalog UI |
| Artifacts | Uploads, workspaces, outputs, checksums, TTL, shared storage | Workflow compilation |
| Scheduling | Recurrence rules and scheduled run creation | Running task code |
| Runtime Environments | Packages, container images, environment health | User sessions |
| Audit and Operations | Audit log, system events, backups, metrics | Business-specific science code |

## Service/process layout

A single repository can contain multiple deployable processes:

- `api`: FastAPI application. Handles HTTP, auth, validation, and application-service calls.
- `worker`: claims task rows, launches task containers, streams logs, writes task outcomes.
- `scheduler`: evaluates schedules and creates due runs transactionally.
- `artifact-janitor`: applies TTL rules, packages outputs, deletes expired workspaces.
- `frontend`: Next.js app served separately or behind a reverse proxy.
- `postgres`: durable database.
- `reverse-proxy`: Nginx, Caddy, Apache, or an institutional gateway.

Optional later services:

- `redis`: only if Postgres-backed queues are insufficient.
- `minio`: if an S3-compatible artifact store is preferable to a mounted volume.
- `observability`: Prometheus, Grafana, Loki, or an institution-provided stack.

## Repository shape

A clean monorepo layout:

```text
BioPipeline2/
  README.md
  docs/
    architecture/
    authoring/
    operations/
    api/
    adr/
  backend/
    pyproject.toml
    alembic.ini
    app/
      main.py
      api/
        v1/
      application/
      domain/
      infrastructure/
      workers/
      settings.py
      telemetry.py
    tests/
  frontend/
    package.json
    src/
      app/
      features/
      components/
      lib/
      generated/
      tests/
  contracts/
    openapi.json
    schemas/
  deploy/
    compose/
    systemd/
    nginx/
    podman/
  scripts/
    dev/
    ops/
  examples/
    pipelines/
    workflows/
    publications/
```

## Backend layers

### Domain layer

Pure models and invariants. No FastAPI, SQLAlchemy session, filesystem, subprocess, or HTTP dependency.

Examples:

- `PipelineDefinition`, `PipelineRevision`.
- `Pipeline`, `PipelineRevision`, `PipelineInput`, `StageSpec`, `TaskPlan`.
- `Publication`, `PublicationRevision`, `FieldSpec`.
- `Run`, `Task`, `TaskAttempt`.
- `Artifact`, `Workspace`, `Schedule`.

### Application layer

Use cases and transactions. This layer coordinates repositories and domain services.

Examples:

- `CreatePipelineRevision`.
- `ValidateWorkflow`.
- `CompileWorkflow`.
- `PublishPipelineRevision`.
- `SubmitCatalogRun`.
- `CancelRun`.
- `ClaimNextTask`.
- `RecordTaskAttemptResult`.
- `AdvanceDueSchedules`.

### Infrastructure layer

Adapters for Postgres, file/artifact storage, container execution, auth sessions, logging, package inspection, and external integrations.

### API layer

Thin route handlers that translate HTTP requests into application commands and queries. Route modules should not contain orchestration logic.

## Data flow

### Admin authoring flow

1. Admin creates or edits a pipeline definition or workflow template.
2. Backend validates the source document.
3. Backend compiles it into a normalized workflow intermediate representation.
4. Backend stores an immutable pipeline revision.
5. Admin previews the public input contract and sample task plan.
6. Admin creates a publication revision from that pipeline revision.
7. Admin publishes it to the catalog.

### Researcher run flow

1. Researcher opens a published catalog entry.
2. Frontend renders the publication revision fields from schema returned by the API.
3. Researcher supplies values, uploads files, or chooses shared-storage inputs.
4. API validates values against the workflow input contract and publication policy.
5. API creates a run and task plan rows transactionally.
6. Worker claims tasks and executes them in isolated containers.
7. Outputs are stored as artifacts and shown in My Runs.

### Scheduled run flow

1. Scheduler claims due schedules using Postgres locks.
2. Scheduler creates runs with the saved schedule input set.
3. Runs enter the same orchestration path as manual runs.
4. Schedule history records success, failure, skipped windows, and next fire time.

## Why Postgres-backed orchestration first

A separate broker is not required for the first rebuild. PostgreSQL can safely support task claiming with `FOR UPDATE SKIP LOCKED`, transactional run creation, schedule claiming, audit events, and outbox messages. This reduces operational complexity on a single Linux VM.

Add Redis, RabbitMQ, or a dedicated workflow engine only when there is measured pressure:

- Very high task throughput.
- Need for delayed retries at scale.
- Need for distributed fan-out across many worker nodes.
- Strict workflow semantics better served by Temporal, Argo, or Airflow.

For this project, a clear domain model is more important than introducing a heavy workflow engine too early.


## Review additions

> Findings below are registered with evidence, severity, and status in
> [gaps.md](gaps.md). This section says what to do about them.

### Missing consumers of the domain layer

The process list covers server-side runtime but omits every non-browser consumer
the current system has: a CLI (`bio-pipeline`), a Python/notebook client, and a
self-contained MCP server exposing about 70 tools over the HTTP API. Whether each
survives is a decision recorded in
[10-feature-parity-and-scope.md](10-feature-parity-and-scope.md), but the
architecture must state the rule now, because it changes the layering:

- The application layer is the only place use cases live, so an in-process CLI is
  a thin adapter over it - the same relationship the API layer has.
- Any out-of-process consumer (notebook client, MCP server) is an OpenAPI
  consumer, not a code consumer, and must be generated or contract-tested. The
  legacy MCP server hand-mirrors ~70 routes; that is what makes a rename a
  breaking change across three repositories at once.
- An admin bootstrap path that does not require a running frontend is a hard
  requirement regardless: something must create the first admin user.

### Missing process: outbox relay

`outbox_events` appears in the data model with no process to drain it. Either
assign it (`worker`, `artifact-janitor`, or a dedicated `relay`) or drop the
table until there is a consumer.

### Missing bounded contexts

Two contexts are implied elsewhere but absent from the table:

- **Notifications**, if the "email" adapter listed under the infrastructure layer
  is real. Nothing else in the plan sends anything.
- **AI Assistance**, if the current AI Designer is carried. It owns conversations,
  tool invocations, provider configuration, and a data-egress boundary - it is not
  a feature of another context.

Both are decisions in [13-open-questions.md](13-open-questions.md). Whichever way
they go, the table should not silently omit them.

### Configuration strategy

The repository shape shows `settings.py` and the deployment section shows a `.env`
file, but there is no configuration strategy. The current system uses one
`configs/app_config.yaml` with environment profiles shared by frontend and
backend. Decide and document:

- Precedence: defaults, then file, then environment variables.
- Validation at boot: fail fast on a missing or malformed required setting, and
  log the effective configuration with secrets redacted.
- Which settings the frontend may read, and how they reach it (build-time
  inlining versus a runtime config endpoint). A runtime endpoint is required if
  one image must serve multiple deployments.
- Where secrets live and how they are rotated - never in the same file as
  ordinary settings.
- Path prefix and base URL handling, since document 06 requires deployment under
  a prefix such as `/biopipeline` from the beginning.

### The task entry-point contract is an architectural boundary

Principle 6 says scientific code runs in isolated task containers, and document
01 credits the current design for keeping science packages external. Nothing
states how a workflow names a callable inside a container. That contract is as
important as the API contract: it is what lets science packages evolve
independently of the platform. Specify it in Phase 1 and version it. See the
detail added to [06-execution-and-operations.md](06-execution-and-operations.md).

### Repository shape additions

Add to the layout:

- `cli/` or a console-script entry point in `backend/`, if a CLI survives.
- `mcp/` if the MCP server is carried in this repository, or a stated decision
  that it stays separate and consumes the published OpenAPI.
- `images/` for runtime environment image definitions - immutable task images
  need source-controlled definitions somewhere.
- `docs/ai/` per document 08's rule, so agent-facing context files never sit
  beside product architecture.
- `.github/workflows/` or the equivalent - see
  [12-testing-ci-and-release.md](12-testing-ci-and-release.md).
