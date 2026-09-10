# Critical Review of the Current System

## Current system in one sentence

The current project is a local-first pipeline manager that grew into a multi-user workflow publishing platform without re-normalizing its domain model, persistence model, or runtime boundaries.

## What the current project does well

The existing system has several ideas worth preserving:

- It separates scientific functions from the manager. The pipeline engine calls external lab/science packages instead of embedding domain-specific algorithms in the platform.
- It supports authored pipeline YAML, higher-level job definitions, matrix and fan-out execution, dependencies, and recurring schedules.
- It has a useful published-job workflow: admins expose curated jobs and researchers submit runs without editing YAML.
- Run workspaces use path containment and manifests, which is a strong security pattern for file uploads and generated outputs.
- Typed values and the type library are a good foundation for structured scientific inputs.
- There is meaningful test coverage around job definitions, queue behavior, workspaces, published runs, and typed fields.
- Documentation exists for several complex features, even when some of it has drifted.

The problem is not that the project lacks ideas. The problem is that the ideas were added in layers around early abstractions that no longer fit.

## Main architectural drift

### 1. The word "job" is overloaded

In the code and UI, "job" may refer to:

- A single queued executable task.
- A multi-stage job definition YAML document.
- A job group created from one definition submission.
- A published job visible to researchers.
- A published run created from a catalog submission.
- A recurring execution of a published job.

This makes routes, models, UI pages, and docs harder to reason about. BioPipeline2 should use precise nouns:

- PipelineDefinition: reusable scientific pipeline logic.
- WorkflowTemplate: admin-authored orchestration around one or more pipelines.
- WorkflowRevision: immutable compiled version of a workflow.
- Publication: curated catalog entry exposed to researchers.
- Run: one execution requested by a user or schedule.
- Task: one executable unit within a run.
- Schedule: a recurrence rule that creates runs.

### 2. YAML is both source code and runtime state

Pipeline YAML and job definition YAML are treated as authoring artifacts, runtime inputs, persisted source, and sometimes rendered intermediate state. Published runs render job definition text by applying fields and bindings, then submit that rendered text back into the queue.

This makes it difficult to answer basic questions:

- Which exact workflow version produced this run?
- Which values were supplied by a researcher versus defaulted by an admin?
- Which fields are part of the public contract and which are internal YAML implementation details?
- Is a published job still valid after its underlying YAML file changes?

BioPipeline2 should compile authoring YAML into an immutable workflow intermediate representation. Runs should point to a workflow revision and store submitted values separately.

### 3. Published fields do too many things

The published job field model currently covers:

- UI labels, help text, order, and visibility.
- Primitive and typed validation.
- Bindings into job definition paths or stage parameters.
- File and directory source policy.
- Input and output path routing.
- Saved typed value behavior.

This creates a fragile binding layer. A field is not just a form field; it can mutate a nested YAML structure. In BioPipeline2, fields should describe the public input contract, while workflow compilation should define how those inputs feed task plans. UI schema, validation, and execution binding should be related, but not collapsed into one object.

### 4. Storage is split across incompatible models

The current runtime combines:

- Filesystem YAML stores.
- SQLite tables for jobs, job groups, materialized stages, published jobs, published runs, auth, installs, saved values, and recurrences.
- JSON blobs inside SQLite columns.
- Workspace manifests and artifact folders.
- A YAML type library file.

This was practical for a local-first prototype, but it makes cross-object consistency, migrations, auditing, backup, and multi-process operation harder. BioPipeline2 should use PostgreSQL as the system of record and reserve the filesystem for large artifacts and execution workspaces.

### 5. The API process owns too much runtime behavior

The current FastAPI lifespan starts the worker, reaper, and recurring schedulers. This is convenient in development but fragile in production:

- Multiple API replicas could duplicate scheduler work.
- Long-running execution is coupled to web serving.
- Worker failures and API failures are not isolated.
- Deployment scaling is unclear.

BioPipeline2 should run separate containers for API, worker, scheduler, and artifact cleanup. They can share the same backend codebase but must have independent process responsibilities.

### 6. The backend lacks clear application-service boundaries

Stores, routes, orchestration, rendering, validation, scheduling, and workspace behavior are spread across large modules. Examples include the published jobs route module, the published job store, and the job queue.

BioPipeline2 should use explicit layers:

- Domain models: pure objects and invariants.
- Application services: use cases and transactions.
- Infrastructure adapters: Postgres, artifact storage, container execution, email, auth.
- API routes: thin request/response adapters.

### 7. The frontend mirrors backend drift

The frontend has valuable functionality, but several pages hold too much state and business logic. The published-job researcher page, published-job admin page, queue panel, and definition panel each coordinate many server resources manually.

BioPipeline2 should organize UI by feature and use generated API types, query-backed server state, focused form components, and role-specific navigation.

### 8. Documentation drift is visible

The existing docs are useful, but not consistently authoritative. Examples:

- Some docs describe older labUtils-backed execution even though the engine is now local.
- Run workspace cleanup behavior differs between docs and code.
- Type docs say typedness belongs in the type library, while code still supports inline definitions in job YAML.
- AI and MCP docs are sometimes historical context rather than current architecture.

BioPipeline2 should define doc ownership rules and require docs to be updated as part of feature work.

## What to keep

Preserve these ideas in the redesign:

- YAML or declarative authoring for scientists and admins.
- Separate scientific code packages from platform orchestration.
- Multi-stage workflows with dependencies, fan-out, and matrix expansion.
- Published catalog for researcher-facing runs.
- Typed structured fields and saved values.
- Workspace isolation, path containment, and output packaging.
- Admin and researcher roles.
- Auditable runs and logs.
- Local VM deployment as a first-class target.

## What to replace

Replace these patterns rather than carrying them forward:

- Mutable YAML-as-runtime-state.
- SQLite as the core system of record.
- Generic JSON text storage for essential state transitions.
- Published field bindings that patch arbitrary YAML paths.
- Worker, scheduler, and cleanup loops inside the API process.
- Large route modules that own business logic.
- Monolithic frontend pages that manually coordinate server state.
- Documentation that mixes operator guidance, historical notes, and agent instructions without clear labels.

## Core lesson

The next project should not begin with "pipelines plus jobs." It should begin with an explicit workflow platform model:

1. Author definitions.
2. Validate and compile them.
3. Publish curated revisions.
4. Submit runs against immutable revisions.
5. Execute tasks in isolated workers.
6. Store artifacts and provenance durably.
7. Document each boundary as a contract.


## Review addition: the inventory is incomplete

> Findings below are registered with evidence, severity, and status in
> [gaps.md](gaps.md). This section says what to do about them.

The diagnosis in this document is accurate, but its "what to keep" and "what to
replace" lists are not a complete inventory of the current system. Checked
against the source tree, the following subsystems exist today and appear nowhere
in this document or in documents 02-09:

- The **AI Pipeline Designer**: an admin chat surface with a multi-provider
  backend, a bounded tool loop, per-turn iteration and wall-clock budgets, and
  server-side-only API keys.
- A self-contained **MCP server** exposing the HTTP API as roughly 70 tools over
  two transports (stdio for a local desktop client, streamable HTTP with a bearer
  guard for remote connectors). It shares no code with the backend and mirrors
  route shapes by hand.
- The **CLI** (`bio-pipeline`), which is also the only way to bootstrap the first
  admin user, and a **Python/notebook client**.
- **Pipeline and job-definition template galleries**.
- **UI-driven package install and uninstall** with an install audit database, and
  **package introspection** (list and search installed functions and classes, read
  a signature) which is how an admin discovers callable science functions.
- **In-app backup and restore** with its own admin page.
- A unified **`configs/app_config.yaml`** with environment profiles shared by the
  frontend and the backend.

Three capabilities of the published-job workflow are also absent from the lists:
**chunked/resumable uploads**, **`url` as an input source** (server-side fetch),
and **delivery of outputs into allowlisted shared storage**. The first two are
implemented in the published-jobs route and store; the third is what the run
reaper does when an output field declares `delivery: ["shared"]`.

Omission from a critical review reads as a decision to drop. None of these were
decisions. They are now tracked, with an owner and a verdict required for each,
in [10-feature-parity-and-scope.md](10-feature-parity-and-scope.md).

One correction to this document's "what to replace" list: replacing UI package
installs with immutable runtime images is the right call, but it removes a
capability admins use today. It is a replacement that owes users a new workflow -
image definition, build, promotion, rollback, and introspection - not a simple
deletion.
