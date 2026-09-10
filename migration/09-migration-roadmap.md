# Migration Roadmap

## Strategy

**There is no migration.** BioPipeline2 starts with an empty database. The
twelve existing pipelines and twelve job definitions are re-authored by hand in
the new format, which is the first real test of that format. The existing
deployment stays available for reference until people have moved (ADR 0018,
ADR 0019).

That deletes the strangler pattern, the importers, the parallel-run comparison,
and most of the cutover risk this document originally described.

What remains is ordinary greenfield sequencing, with one rule: **prove the
riskiest assumptions first.** The original plan put the frontend at phase 6 and
import at phase 8, which meant the two things most likely to invalidate the
design were tested after the schema, compiler and API had hardened around
assumptions.

## Phase 0 — Decisions and feasibility

Goals:

- Close the blocking ADRs. 16 of 30 are decided; ADR 0013 (shared-storage
  identity) is the remaining hard blocker, and shared-storage access is not
  built until it is answered.
- Take one real pipeline — `growth_rates_pipeline.yaml` with its
  `mapping_file` fan-out over 13 experiments — express it in the new format by
  hand, run it in a container, and compare the output to the current system's.
- Name the pipelines that must work on day one (ADR 0016).

Acceptance:

- One real pipeline produces equivalent scientific output through the new
  execution path.
- The task entry-point contract survives contact with a real `labUtils` call.

Status: **the contract and the schema exist; the spike has not been run.**

## Phase 1 — Contracts and schema

Goals: domain vocabulary, Pydantic models, the base Alembic migration,
generated OpenAPI, generated TypeScript client, seed data.

Acceptance:

- A fresh database migrates to head, and models and migrations agree.
- A seed command produces a working admin, pipeline, publication and type.
- The frontend can call `/auth/session` and `/catalog` through the generated
  client.

Status: **largely complete.** 33 tables, the lifecycle state machines, the task
contract, resource admission control, and 153 tests. The API and seed command
are not written.

## Phase 2 — Walking skeleton

One thin vertical slice through every layer, before anything is built out:
minimal compiler, a one-stage pipeline, run creation, one worker, one container,
one artifact, and a crude page showing status and a download link.

This is what proves the boundaries and the deployment shape while they are still
cheap to change.

Acceptance: a real pipeline submitted through the API executes in a container
and produces a downloadable artifact.

## Phase 3 — Compiler

Goals: parse the authoring document, resolve `{brace}` references and bare-name
dataflow, expand the `variables` matrix, plan the three fan-out kinds, and
compile to an immutable IR with diagnostics.

Acceptance:

- All twelve existing pipelines and twelve job definitions are expressible.
- The compiler rejects: cycles, unknown references, unresolvable references,
  bindings to nonexistent stages/steps/parameters, `{item.*}` outside a fan-out
  stage, type mismatches, and unsafe paths.
- Compilation is deterministic: the same source twice yields the same
  `graph_hash`.

## Phase 4 — Orchestration and execution

Goals: materialise tasks from the IR including deferred fan-out, claim under
resource admission control, run containers against an environment snapshot,
stream logs, verify declared outputs, promote artifacts, handle retries,
cancellation, lease expiry and orphan reconciliation.

Acceptance:

- A two-stage dependent pipeline runs end to end.
- A `mapping_file` fan-out materialises the right task set.
- Killing a worker mid-task recovers without manual intervention.
- Two workers never run the same task; the budget is never over-committed.
- A cancelled run converges to `cancelled` with no live worker.

Partially done: claiming, leases, admission control and their tests exist.

## Phase 5 — Publications and catalog

Goals: publication revisions from pipeline revisions; field configuration with
publish-time binding resolution; the researcher catalog and submission form;
typed values with submit-time coercion; saved values.

Acceptance:

- An admin publishes without hand-editing bindings, and a binding to a
  nonexistent target fails at publish.
- A researcher submits with uploaded files, shared-storage selections and typed
  values.
- Typed values are coerced; bad coercion fails the request with a field-level
  error.
- A run records the exact publication revision, pipeline revision, environment
  snapshot and submitted values.

## Phase 6 — Environments and package management

Promoted from an afterthought: in a generic Python executor, "what can I call?"
*is* the authoring experience.

Goals: install, uninstall and list packages; per-run environment snapshots;
function and signature introspection; install-history provenance; editable-
install detection.

Acceptance:

- An install during a running task does not affect it.
- A run records the package set it used.
- An editable install is detected and the run marked non-reproducible.
- An admin can search installed callables and read a signature.

## Phase 7 — Scheduling, retention and delivery

Goals: schedules creating ordinary runs; TTL cleanup; the janitor; output
packaging with a manifest fallback above the size threshold; shared-storage
delivery with its own retry.

Acceptance:

- A schedule fires exactly once across a scheduler restart at the moment of
  firing.
- Outputs stay downloadable until expiry; cleanup is idempotent and audited.
- A failed shared-storage delivery is visible and retryable.

## Phase 8 — Frontend

Built on the skeleton rather than as a big-bang rebuild: role-based shell,
pipeline editor with compiler diagnostics, publication editor and preview,
catalog and submission, My Runs, run detail, schedules, saved values, the
environment and package browser, and admin operations.

Acceptance:

- Playwright: login, catalog, submit, monitor, download.
- Playwright: create a pipeline revision, publish, inspect a run.
- Large-upload behaviour: chunk retry, resume, cancel.
- Failures are filterable rather than needing deletion to keep the list
  readable.
- Works under a path prefix.

## Phase 9 — Operations hardening

Goals: deployment documentation, health and readiness endpoints, structured
logs, metrics and alert thresholds, backup and restore, upgrade with worker
draining, rollback.

Acceptance:

- A clean Linux VM install succeeds from the documentation.
- Backup and restore tested, with a database-versus-artifact reconciliation
  reporting zero orphans.
- An upgrade with a migration is rehearsed, and a day-long task survives it.

## Phase 10 — Adoption

Not a cutover, since no data moves. Re-author the remaining pipelines, publish
them, move the users across, and retire the old deployment on a stated date
(ADR 0017, ADR 0020).

## Risk register

| Risk | Mitigation |
| --- | --- |
| The new format cannot express a real pipeline | Phase 0 spike before the compiler hardens |
| Re-authoring twelve pipelines by hand is more work than expected | It is also the format's acceptance test; count the effort in Phase 0 |
| Windows paths throughout the existing YAML | Translate during re-authoring; no importer will do it |
| RNA-seq workloads exhaust the VM | Resource admission control; budgets set below real capacity |
| A day-long task blocks upgrades | Worker draining plus expand/contract migrations |
| Environment snapshots cannot capture editable installs | Detect and mark the run non-reproducible rather than claim provenance |
| Shared storage accessed as a service account bypasses institutional permissions | **Unresolved.** ADR 0013; nothing is built on it |
| The compiler becomes too rigid for real pipelines | The twelve existing definitions are the regression suite |
| Silent failures like the 23% unresolved-reference finding recur | Compile-time rejection; publish-time binding validation |
| Documentation drifts again | Metadata and staleness CI checks in document 08 |

## Definition of done for v1

- No `Decision needed` ADR remains open, or each is consciously deferred.
- An admin can author, validate and publish a pipeline revision.
- A researcher can submit with typed inputs, uploads and shared-storage
  selections.
- Tasks execute in containers against a recorded environment snapshot.
- Heavy tasks run sequentially without starving short ones.
- A worker can be killed at any point without stranding work.
- A running task can be cancelled and converges without intervention.
- Run detail shows the task graph, logs, inputs, outputs, deliveries and
  downloads; failures are filterable.
- Schedules create ordinary runs, exactly once per window.
- Restore is tested; an upgrade with a migration is rehearsed.
- Deployment works on a Linux VM under a path prefix.
- The named day-one pipelines produce equivalent output and their owners sign
  off.
