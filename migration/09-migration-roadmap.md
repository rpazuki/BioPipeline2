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

Status: **ADR 0013 is decided; the spike has been run and passes, and it found
eight defects on the way.** Details below.

### Phase 0b, as actually run

`make spike` (`scripts/dev/spike.py`) compiles
`examples/pipelines/od600_growth_rates.yaml`, fans it out over a mapping file
into six tasks — two matrix rows across three plate-reader exports — executes
each in a container, and reports what happened.

**What it proved.** A green run, end to end:

```text
run: succeeded
  succeeded  fit:no_replicates:plate_01 … fit:replicates:plate_03   (6 tasks)
  artifacts: 12     deliveries: 6 delivered
  mu_max expected 0.346574 (doubling every 2h)
  12 series checked, 0 wrong
```

The document compiles through the API, the matrix and the `mapping_file`
fan-out expand to the right six tasks, containers launch under the containment
baseline with the science library mounted and importable, the runner chains
steps by reference (`raw_data: raw_data`, `df: df_parsed`), payload eviction
releases each intermediate as it becomes dead, declared outputs land where the
platform looks for them, and they are promoted to checksummed artifacts with
their deliveries recorded.

The last two lines are the ones worth having. The synthetic data doubles every
two hours, so the maximum growth rate is `ln(2)/2` exactly; the spike asserts
it rather than printing it. That makes this a correctness check within the
platform's reach, not merely "nothing crashed" — the values that came out of
the far end are the values that should have.

The step-chaining style was checked against the lab's own
`growth_rates_pipeline.yaml` rather than assumed. The real file writes
`raw_data: raw_data` and `df: df_transformed` exactly as the runner expects, so
the contract's data flow **is** the data flow real pipelines already use. That
was the single largest open risk in this plan and it is retired.

**What it did not prove**, and cannot here: `labUtils` is a standard-library
stand-in with the real module paths, call names and argument names, so nothing
is established about the real library; and with no reference outputs there is
nothing to compare scientific results against. Acceptance therefore remains
open on "equivalent scientific output" and "a real `labUtils` call" — both need
the lab's package and a reference run.

**What it found.** Eight defects, every one invisible to the test suite, and
five of the same species: a seam declared, documented, unit-tested, and never
connected to anything.

| # | Defect |
| --- | --- |
| 1 | **The component library loader was never wired into the API.** `create_revision` took a `load_library` argument, `DirectoryLibraryLoader` existed and was tested, and no route passed one — so every document with a `uses:` answered `component.no_loader`. That is most real pipelines, since pervasive reuse is why ADR 0026 kept components at all. |
| 2 | **`FanOutEnumerator` had no implementation anywhere.** The protocol was declared, `materialise` accepted one, `submit_run` forwarded one, the API passed `None`. Any stage that fanned out was unsubmittable — and one task per plate-reader export is the ordinary shape of this work, not an edge case. |
| 3 | **Shared-storage roots were never mounted into a task container.** `DockerAdapter.extra_mounts` was documented for exactly this and populated by nothing outside its own unit test. |
| 4 | **Science libraries were never mounted either.** ADR 0028 says they are mounted at run time rather than baked into the image; nothing mounted them, so no task could import anything beyond the standard library. |
| 5 | **`TaskSpec.stage_key` rejected matrix variants.** The compiler writes `fit:no_replicates`; the field was typed `Identifier`, which forbids `:`. Every pipeline with a matrix compiled, submitted, materialised and got claimed, then failed to build its task specification. The unit fixtures have one stage and no variant, so nothing caught it. |
| 6 | **Absolute input paths were silently made relative.** `build_spec` did `value.lstrip("/")` to satisfy a relative-path type, turning `/mnt/lab/plate.csv` into a lookup under the workspace. Nothing failed loudly: the container reported a missing file at a path nobody had written. |

Two more were design errors rather than disconnected seams, and both are
specifically about fan-out — which is why nothing had caught them:

**`output_dir` pointed at a fixed `outputs/`**, while every task of a run
shares one workspace. Six fanned-out tasks all wrote to the same directory,
overwrote each other, and then failed verification having produced perfectly
good files in the wrong place. It now points at the task's declared output
directory, which already carries whatever separates it from its siblings.

**A delivery was unique on `(run_id, field_key, mode)`**, which reads correctly
until six tasks each produce an output called `results`. The second task's
promotion violated the constraint — and did not fail that task: the error
raised out of promotion, out of the worker's claim loop, and stopped every
other queued task with it. One bad task idled the machine. Uniqueness now sits
on `(artifact_id, mode)`, which is what "deliver this file there" means, a
delivery records the task that produced it, and a promotion failure fails its
task rather than the worker.

Two further findings were in the fixtures rather than the platform, and are
worth recording because they are the mistakes authors will make: the example
component library omitted the parameters that chain one step to the next, and
its replicates graph fitted a column it never computed.

**The lesson the roadmap already predicted.** Every one of these sat behind a
green test suite. A unit test of a component in isolation cannot observe that
nothing calls it, and a fixture with one stage and one task cannot observe
anything that only breaks when a stage fans out — which was three of the eight.
The plan's own rule, prove the riskiest assumptions first, was right; running
this before the API and the frontend would have saved building on eight broken
joints.

`make spike` keeps it runnable, and it asserts rather than reports, so it
fails if any of the eight comes undone.

## Phase 1 — Contracts and schema

Goals: domain vocabulary, Pydantic models, the base Alembic migration,
generated OpenAPI, generated TypeScript client, seed data.

Acceptance:

- A fresh database migrates to head, and models and migrations agree.
- A seed command produces a working admin, pipeline, publication and type.
- The frontend can call `/auth/session` and `/catalog` through the generated
  client.

Status: **complete.** 32 tables, the lifecycle state machines, the task
contract, resource admission control, the API, the generated TypeScript client
with its freshness gate, `make seed`, and 551 tests.

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

### Scheduling, as actually built

The scheduler loop exists (`app/workers/scheduler.py`) over the recurrence
arithmetic in `app/domain/recurrence.py` and the transactional firing in
`app/application/schedules.py`. ADR 0015 is accepted; the rules are in
[06](06-execution-and-operations.md) under "Scheduling".

The first acceptance criterion holds by construction rather than by care: the
window is staked in `schedule_fires` before anything is created, so a restart
at the moment of firing either committed the whole transaction or none of it.
A second, independent guarantee is the run's idempotency key
`schedule:<id>:<window>`.

Two things the schema could not have told us, both found writing the loop:

- **`now()` cannot order a history.** PostgreSQL's `now()` is the transaction
  timestamp, so the several `schedule_events` one tick writes shared it and a
  time-ordered view showed them shuffled. `schedule_events.created_at` now
  defaults to `clock_timestamp()`.
- **"Shift forward" must shift, not clamp.** Clamping a nonexistent local time
  to the end of the DST gap reads better and is wrong: two windows inside the
  gap would land on one instant, and the second would be swallowed by the
  unique constraint meant to guarantee it a run.

Schedules have a REST surface and a screen: compose one from a catalog entry
using the same form the catalog renders, see what it will run and when in
words rather than as an RRULE, and read back what each window actually did.

Shared-storage delivery is built, with its own process and its own retry; so
is the generation janitor, which removes the environment builds no run can
still reach and keeps the row that says what they contained.

Still outstanding in this phase: output packaging above the size threshold,
and retention for `audit_events`, which ADR 0001 has not yet given a number.

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
