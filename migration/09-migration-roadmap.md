# Migration Roadmap

## Strategy

Build BioPipeline2 as a new project rather than refactoring the existing code in place. Use a strangler migration: preserve the useful concepts, write importers for legacy artifacts, and run old and new systems in parallel until core workflows are proven.

Do not begin by porting every route and page. Begin by locking down the new domain model and contracts.

## Phase 0: Inventory and freeze

Goals:

- Inventory existing pipeline YAML files, job definition YAML files, published jobs, type library entries, users, saved values, schedules, and run workspaces.
- Identify which historical runs must be preserved versus archived externally.
- Freeze new feature work in the old architecture except urgent fixes.
- Choose initial deployment style: Docker Compose or Podman Compose.

Outputs:

- Legacy inventory report.
- Migration acceptance checklist.
- Initial BioPipeline2 repository scaffold.
- ADRs for Postgres, process separation, and workflow IR.

## Phase 1: Contracts and schema

Goals:

- Define domain vocabulary.
- Write Pydantic models for pipeline revisions, workflow revisions, publications, runs, tasks, fields, artifacts, schedules, and types.
- Create Alembic base migration.
- Generate OpenAPI from FastAPI.
- Generate TypeScript client from OpenAPI.

Acceptance criteria:

- Fresh database migrates to head.
- Seed script creates admin user, sample pipeline, workflow, publication, and type.
- Frontend can call `/auth/session` and `/catalog` through generated client.

## Phase 2: Workflow compiler

Goals:

- Parse new workflow YAML.
- Validate inputs, stages, dependencies, fan-out, and output declarations.
- Compile to immutable workflow IR.
- Store workflow revisions in Postgres.
- Provide compile preview endpoint and diagnostics.

Acceptance criteria:

- Existing representative job definitions can be expressed in the new workflow format.
- Compiler rejects cycles, missing inputs, invalid types, and unsafe paths.
- Compile output is deterministic and hashable.

## Phase 3: Run orchestration and task execution

Goals:

- Create runs from workflow revisions.
- Materialize task rows from compiled IR.
- Implement Postgres task claiming.
- Implement local container execution adapter using Docker or Podman.
- Store logs and outputs as artifacts.

Acceptance criteria:

- A sample workflow with two dependent stages runs end to end.
- A fan-out workflow materializes dynamic tasks correctly.
- Failed task attempts are visible with logs.
- Cancellation works for queued and running tasks.

## Phase 4: Publications and researcher catalog

Goals:

- Create publication revisions from workflow revisions.
- Configure field labels, defaults, source policies, grouping, and visibility.
- Render researcher catalog and submission form.
- Submit runs through publication contract.
- Support saved values and typed structured inputs.

Acceptance criteria:

- Admin can publish a workflow without editing YAML bindings.
- Researcher can submit a catalog run with uploaded files and typed values.
- Submitted run records exact publication revision, workflow revision, and input values.
- Invalid values fail with useful field-level errors.

## Phase 5: Scheduling and retention

Goals:

- Add schedules that create normal runs.
- Add artifact retention policy.
- Add janitor process.
- Add output packaging and download.

Acceptance criteria:

- Schedule creates due runs once and only once.
- Missed windows are recorded according to policy.
- Outputs remain downloadable until expiration.
- Cleanup is idempotent and audit logged.

## Phase 6: Frontend rebuild

Goals:

- Build role-based shell.
- Build admin workflow editor and compiler diagnostics.
- Build publication editor and preview.
- Build researcher catalog and run submission.
- Build My Runs, run detail, schedules, and saved values.
- Build admin runs and operations pages.

Acceptance criteria:

- Critical researcher flow passes Playwright test: login, catalog, submit, monitor, download.
- Critical admin flow passes Playwright test: create workflow revision, publish, inspect run.
- UI works under `/biopipeline` path prefix.

## Phase 7: Operations hardening

Goals:

- Write deployment docs.
- Add health checks.
- Add structured logs and metrics.
- Add backup and restore scripts.
- Add upgrade and rollback procedure.
- Add runtime environment health checks.

Acceptance criteria:

- Clean Red Hat VM install succeeds from docs.
- Backup and restore tested.
- Upgrade with migration tested.
- Worker restart does not lose task state.

## Phase 8: Legacy importers

Import only what is valuable. Do not replicate every historical quirk.

### Import pipeline YAML

- Read legacy `yamls/` files.
- Create `pipeline_definitions` and `pipeline_revisions`.
- Preserve original text as source.
- Store validation warnings if syntax depends on old behavior.

### Import job definitions

- Read legacy `job_defs/` files.
- Convert simple cases to new workflow templates.
- Flag complex legacy bindings for manual migration.
- Produce a report for each conversion.

### Import type library

- Read legacy `type_library.yaml`.
- Create versioned `type_definitions`.
- Reject or quarantine invalid entries.

### Import published jobs

- Read legacy published jobs from SQLite.
- Create publication drafts, not automatically published entries.
- Map fields to workflow inputs where possible.
- Flag arbitrary YAML path bindings for manual review.
- Preserve old description and display metadata.

### Import users and saved values

- Import users if password hashing and auth policy allow it.
- Otherwise create user stubs and force password reset.
- Import saved values after type definitions are imported.

### Import historical runs

Prefer exporting old runs to a read-only legacy archive rather than fully importing them. If importing is required, mark them as legacy records with immutable metadata and links to archived artifacts.

## Phase 9: Parallel run and cutover

Goals:

- Run old and new systems side by side.
- Select a small set of representative workflows.
- Compare outputs, logs, and operator experience.
- Train admins and researchers.
- Freeze old system submissions.
- Switch catalog entry points to BioPipeline2.

Acceptance criteria:

- Representative workflows produce equivalent scientific outputs.
- Admins can publish and troubleshoot without developer intervention.
- Researchers can submit and retrieve outputs successfully.
- Backup/restore is proven.
- Old system remains available read-only for a defined retention period.

## Risk register

| Risk | Mitigation |
| --- | --- |
| Legacy published fields cannot map cleanly to new workflow inputs | Import as drafts and generate manual review reports. |
| Container execution differs from current subprocess execution | Start with known sample workflows, lock runtime images, compare outputs. |
| Users depend on old terms like Published Jobs | Keep UI compatibility labels while using clean internal nouns. |
| Red Hat environment restricts Docker | Support Podman adapter and document SELinux volume labels. |
| Historical runs are expensive to migrate | Archive old runs read-only and migrate only metadata needed for discovery. |
| Workflow compiler becomes too rigid | Keep explicit extension points, but require all extensions to compile to IR. |
| Frontend rebuild grows too broad | Deliver vertical slices: catalog submission, run detail, admin publication, then expand. |

## Definition of done for BioPipeline2 v1

- Admin can create and validate a workflow revision.
- Admin can publish a catalog entry from that revision.
- Researcher can submit a run with typed inputs and uploaded/shared files.
- Worker executes tasks in isolated containers.
- Run detail shows task graph, logs, inputs, outputs, and downloads.
- Schedules create normal runs.
- PostgreSQL migrations, backups, and restore are documented and tested.
- Deployment works on a Red Hat VM under a path prefix.
- Core docs are current and linked from the root README.


## Review additions

> Findings below are registered with evidence, severity, and status in
> [gaps.md](gaps.md). This section says what to do about them.

### The phase order delays proof of the riskiest assumptions

As written, the frontend arrives at Phase 6 and legacy import at Phase 8. That
means the two things most likely to invalidate the design - container execution of
real scientific workloads, and whether legacy published jobs can be expressed in
the new workflow format at all - are proven late, after the schema, the compiler,
and the API are already built around assumptions.

Restructure so that a **walking skeleton** comes first: one real workflow,
end to end, through every layer, on day one of Phase 2 rather than at the end of
Phase 6.

Recommended resequencing, keeping the existing phase content:

| Order | Work | Why here |
| --- | --- | --- |
| 0 | Inventory, freeze, decisions | Unchanged, but must now close the decision queue in [13-open-questions.md](13-open-questions.md) and the ledger in [10-feature-parity-and-scope.md](10-feature-parity-and-scope.md). |
| 0b | **Feasibility spike**: take one real existing job definition, hand-write it in the new workflow format, run it in a container by hand, and confirm the science output matches. | This is the assumption the whole plan rests on. A week here can save a quarter. Also produces the task entry-point contract. |
| 1 | Contracts and schema | Unchanged. Add the task entry-point contract and the expression language specification as deliverables. |
| 2 | **Thin vertical slice**: minimal compiler, one-stage workflow, run creation, one worker, one container, one artifact, one crude UI page showing status and a download link. | Proves every boundary and the deployment shape while it is still cheap to change. |
| 3 | Compiler in full: fan-out, dependencies, diagnostics, determinism | Now grounded in something that runs. |
| 4 | Orchestration in full: retries, leases, cancellation, stale-claim reaping | |
| 5 | Publications and researcher catalog | |
| 6 | Scheduling, retention, delivery | Output delivery to shared storage belongs here and is currently missing from the plan. |
| 7 | Frontend build-out on the slice's foundation | Incremental, not a big-bang rebuild. |
| 8 | Operations hardening | Unchanged. |
| 9 | Legacy importers | Unchanged, but see the missing importers below. |
| 10 | Parallel run and cutover | Unchanged, plus the abort criteria below. |

### Missing importers

Phase 8 lists pipelines, job definitions, the type library, published jobs, users,
saved values, and historical runs. Not listed, and present in the current system:

- **Recurring schedules** (researcher-facing). This is the hardest import in the
  set, because the current model is interval-based ("every N units") and the plan
  proposes RRULE. Every active schedule needs a mapping, a review, and an owner
  notification. A schedule silently not migrating means work stops happening and
  nobody notices for a week.
- **Recurring admin jobs**, which have no successor concept in the new model at
  all. Decide what happens to them.
- **Pipeline and job-definition templates**.
- **Package install audit** (`installs.sqlite`), if the history matters for
  reproducibility - it records what was installed when, which is provenance for
  past runs.
- **Legacy directories not covered by the inventory**: `Jobs_Pipelines_backup/`,
  `outputs/`, `data/sample/`, and `.bio_pipeline/job_defs_archive/`. Each is
  either in scope or explicitly out - do not discover them during cutover.
- **Shared-storage root configuration**, which lives in `configs/app_config.yaml`
  today and is deployment state, not application data.

### Importer requirements

The plan says what to import but not how, and importers that cannot be re-run are
a cutover trap. Require of every importer:

- **Dry-run mode** that produces the full report and writes nothing.
- **Idempotency**, keyed by a recorded legacy identifier, so a re-run updates
  rather than duplicating. Add a `legacy_ref` column (source system, source id,
  source checksum) to every imported entity, or keep a dedicated
  `legacy_import_map` table. Neither exists in document 04.
- **A machine-readable report** per run: counts by outcome, and one row per item
  with `imported`, `imported_with_warnings`, `needs_manual_review`, or `failed`
  plus the reason. This report is the acceptance artefact for Phase 8.
- **Order dependencies stated and enforced**: types before saved values, workflows
  before publications, publications before schedules, users before anything owned.
- **Reconciliation counts**: legacy count versus imported count versus deliberately
  skipped, and a non-zero unexplained difference fails the phase.
- **Bounded manual-review budget.** "Flag complex legacy bindings for manual
  migration" is open-ended. Count them during Phase 0 inventory and decide whether
  the number is affordable; if it is not, the workflow format or the importer needs
  to absorb more cases.

### Missing: abort criteria

The plan has a risk register but no exit. Define before Phase 0 closes:

- The conditions under which the migration stops or is re-scoped: for example the
  feasibility spike failing, or more than N% of published jobs requiring manual
  conversion, or scientific output not matching on the representative set.
- Who decides, and on what evidence.
- What "stop" means in practice: the current system continues, and what happens to
  the work already done.

Also missing: the **duration** of the parallel-run period, the owner of the
cutover decision, and how long the old system stays read-only ("a defined
retention period" is not defined).

### Missing: effort, sequencing, and ownership

A roadmap with ten phases, no estimates, no owners, and no calendar cannot be
used to plan or to say no. Add, even roughly:

- An effort band per phase (weeks, not days, given the scope) and the assumed
  team size. The plan describes work that is plainly larger than one part-time
  developer; if that is the actual resourcing, the scope must shrink and the
  ledger in document 10 is where it shrinks.
- The critical path: decisions in document 13, then the entry-point contract, then
  the compiler, then everything else. Frontend and operations work can proceed in
  parallel once the slice exists.
- What can be cut. Nominate, in advance, which `Carry` rows in document 10 become
  `Defer` if the schedule slips. Deciding this under pressure produces worse
  choices.

### Acceptance criteria to add

Per phase, alongside the existing criteria:

- Phase 0b: one real legacy job runs in a container and the output matches the
  legacy output byte-for-byte or by a stated scientific equivalence check.
- Phase 1: seed script produces a working system; migrations round-trip; the
  committed OpenAPI matches the generated one.
- Phase 4: kill a worker mid-task and the task recovers without manual
  intervention; two workers never run the same task; a cancelled run converges to
  `cancelled` with no live worker.
- Phase 6: a schedule fires exactly once across a scheduler restart at the moment
  of firing; a failed shared-storage delivery is visible and retryable.
- Phase 8: restore rehearsal meets the stated RPO and RTO; a
  database-versus-artifact reconciliation reports zero orphans.
- Phase 9: reconciliation counts balance; every active schedule is either migrated
  or its owner has been told.
- Phase 10: a named list of representative workflows (see document 13, question
  16) produces equivalent outputs, and the researchers who own them sign off.

### Risk register additions

| Risk | Mitigation |
| --- | --- |
| The feasibility of expressing real legacy jobs in the new workflow format is unproven | Phase 0b spike before committing to the schema and compiler. |
| Scope is larger than the resourcing, and the plan has no cut list | Pre-agree which ledger rows become `Defer`; keep the ledger current. |
| Large inputs make HTTP upload unusable and the design has no fallback | Fix the size numbers in document 11 early; keep shared-storage selection as the primary path for large data. |
| Removing UI package installs blocks admins with no replacement workflow | Deliver image build, promote, and rollback in the same phase that removes installs. |
| Interval schedules do not map cleanly to RRULE, and a missed migration is silent | Per-schedule review with owner notification; keep the old system read-only long enough to notice. |
| Session-account access to shared storage bypasses institutional permissions | Decide the identity model in Phase 0; it may require impersonation or per-user mounts. |
| Long-running tasks conflict with the upgrade procedure | Worker draining, expand/contract migrations, stated maximum drain time. |
| The MCP server, CLI, and notebook client silently rot against the new API | Contract tests in CI, or an explicit decision to drop them. |
| The compiled IR changes shape after runs exist | Version the IR and state the compatibility policy. |
| Documentation drifts again | The metadata and staleness CI checks in document 08, treated as build failures. |
| No staging environment, so the import and upgrade are first rehearsed in production | Provision staging in Phase 1, not Phase 9. |

### Definition of done additions

Add to the v1 list:

- The decision queue in document 13 is empty, and each answer has an ADR.
- The parity ledger in document 10 has no `Undecided` rows.
- Load and data-size targets in document 11 are filled in, and the system has been
  tested at them.
- Data governance sign-off obtained, if the platform holds identifiable data.
- A worker can be killed at any point without stranding work.
- A run can be cancelled while running, and converges without manual intervention.
- Output delivery to shared storage works and failures are retryable.
- Chunked, resumable upload of the largest expected input succeeds.
- Restore rehearsal meets the stated RPO and RTO.
- An upgrade with a migration has been rehearsed on staging, and a rollback tested.
- Every active legacy schedule is migrated or its owner notified.
- The named representative workflows are signed off by the researchers who own them.
