# Second Review: Gaps After the Interview and Sample Analysis

Date: 2026-09-10
Status: Open review findings
Scope: Revised migration plan, accepted ADRs, current BioPipeline2 foundation,
and the real deployment material under `bio_pipeline_sample/`

## Overall assessment

The revised plan is substantially better than the original. It now reflects a
generic Python execution and orchestration platform, uses measured workload
data, preserves package installation and callable discovery, and treats silent
compilation failures as correctness defects.

The plan is not yet ready to be the authoritative implementation blueprint.
Two accepted decisions rest on weak or incorrect premises, publication binding
is not internally coherent, and the planning documents and existing foundation
describe different systems. These issues should be resolved before the compiler,
public API, or execution adapter harden around them.

## Evidence reviewed

The sample is stored at `../bio_pipeline_sample/` and contains:

| Evidence | Observed |
| --- | ---: |
| Pipeline YAML files | 11 |
| Named pipeline graph definitions | 15 |
| Unique pipeline graph names | 8 |
| Non-pipeline mapping YAML files | 1 |
| Job-definition files | 12 |
| Unique `job:` names | 7 |
| Preserved task specifications | 2,178 |
| Current SQLite `jobs` rows | 164 |
| Published jobs | 8 |
| Published runs | 31 |
| Run workspaces | 33 |
| Publication fields | 72 |

The 72 publication fields contain 72 bindings: 52 `definition_path`, 18
`stage_process_arg`, and 2 `stage_input_source` bindings.

The fact that all 164 retained `jobs` rows succeeded is not evidence of the
failure rate: failed rows were deleted manually. Reliability conclusions must
come from reproducible execution tests, not the surviving status distribution.

## Findings

### G2-01: The complete Pipeline/Job collapse rests on false reuse evidence

Severity: **Blocker**

ADR 0026 says the two authoring levels are not independently useful and that
every job definition references pipelines created only for that job. It also
says no sample relies on reuse. The sample contradicts both claims:

- The growth-rate graphs in `yamls/growth_rates_pipeline.yaml` are selected by
  four job definitions: the single-file, multiple-file, pattern-based, and
  Alfie variants.
- `downlaod_organism_GEM_pipeline` is reused by three FBA job definitions.
- The same computational graph is combined with different fan-out, input
  routing, defaults, dependencies, and output placement.

The existing boundary is badly named and awkwardly represented, but it
captures two real responsibilities:

1. A reusable computational graph of Python calls.
2. A runnable orchestration scenario that supplies fan-out, variants, routing,
   dependencies, and public parameters.

#### Recommendation

Amend ADR 0026 from Option B to a refined Option C:

- Keep one user-facing product concept, `Pipeline`.
- Let a pipeline revision contain or import reusable compile-time `Component`
  or `StepGroup` definitions.
- Give components no publication, scheduling, run, or independent runtime
  lifecycle.
- Resolve and pin every component by revision or content digest at compilation.
- Expand components completely into the immutable IR, so a run points only to
  `PipelineRevision`.

This preserves the simpler vocabulary requested in the interview without
turning shared computation into duplicated YAML.

#### Closure criteria

- ADR 0026 is amended or superseded.
- At least the four growth-rate job definitions compile without duplicating the
  growth-rate step graphs.
- Both FBA jobs reuse one pinned organism-download component.
- The compiled IR is self-contained and remains executable if an imported
  component later changes.

### G2-02: Publication binding has no coherent target model

Severity: **Blocker**

Document 03 correctly restores flexible publication-field bindings, but says
the current system has only two target kinds. The sample has three:

- `definition_path`
- `stage_process_arg`
- `stage_input_source`

There is also a contradiction across layers:

- Document 03 says an admin may expose any internal value and that bindings are
  resolved into the compiled IR at publication time.
- Document 07 says the publication editor must not patch arbitrary YAML paths.
- The implemented `PublicationField` explicitly carries no binding and can only
  reference a predeclared `PipelineInput` or `PipelineOutput`.

A pipeline revision is already immutable when a publication is created. The
plan does not explain how a new public slot can be added to that IR without
mutating it or creating a derived executable representation.

#### Recommendation

Define an immutable `BindingPlan` owned by `PublicationRevision`:

- Bind to stable semantic identifiers, not array positions in source YAML.
- Supported targets must include pipeline defaults, stage inputs, step
  parameters, outputs, and delivery destinations where appropriate.
- Validate every target and type against `PipelineRevision.compiled_spec` when
  the publication revision is created.
- Store the validated target and expected type in the publication revision.
- At run creation, combine submitted values and the binding plan into a new
  immutable `TaskPlan`; never patch source YAML or mutate the stored IR.
- Preserve the original binding in provenance so an old run remains
  explainable.

The UI can still offer "select a value to expose" rather than asking an admin
to write paths manually.

#### Closure criteria

- One binding schema is used by the domain document, database model, API, and
  frontend.
- All 72 real sample bindings can be represented or have a documented
  conversion.
- Invalid stage, step, input, and parameter targets fail publication.
- A publication can expose an internal constant without producing a mutable or
  ambiguous pipeline revision.

### G2-03: The plan and implemented foundation describe different systems

Severity: **Blocker**

`15-premise-correction.md` says documents 01-14 were updated in place, but
important old decisions remain in active sections:

- Document 02 still separates Pipeline Registry and Workflow Authoring and
  retains `workflows/`, `podman/`, and workflow examples in the repository map.
- Document 05 still defines a complete `/api/v1/workflows` resource beside
  `/api/v1/pipelines`.
- Document 07 still uses workflow routes, query keys, feature folders, and
  screen names.
- Document 08 still requires workflow-template, workflow-expression, legacy
  import, and old ADR documentation.
- Document 04 says type heads and type versions were removed, while its body
  and the implemented models still contain them.
- Document 03 includes an `expired` run status, while ADR 0012 and the lifecycle
  implementation deliberately exclude it.
- The root README says all 25 ADRs are proposed and reports 36 tables; the
  repository has 30 ADRs, 16 accepted, and 33 model tables.
- `ASSUMPTIONS.md` still says Podman, Red Hat, and the old decision state.

The largest implementation conflict is the expression language: ADR 0027 and
document 03 require `{brace}` references, while `app/domain/expressions.py`, its
tests, and the root README still implement and advertise `${{ ... }}`.

#### Recommendation

Perform a single consistency pass with an explicit source-of-truth order:

1. Accepted ADRs.
2. Current domain and architecture documents.
3. Executable contracts and schemas.
4. Implementation and tests.
5. README and operational summaries.

Do not label a gap implemented merely because the earlier implementation has
tests; tests of a superseded contract are evidence of divergence.

#### Closure criteria

- No active API, schema, frontend, or documentation section describes a
  separate Workflow resource unless ADR 0026 is superseded accordingly.
- Expression syntax and namespaces agree across ADR, documentation, code, and
  tests.
- Type lifecycle and run statuses agree across ADRs, models, migrations, and
  documentation.
- Generated checks verify ADR counts, model-table counts, terminology, and
  forbidden superseded syntax.

### G2-04: Per-run virtualenv snapshots are technically unsafe and unproven

Severity: **High**

ADR 0028 proposes a copy-on-write or hardlinked clone of the mutable virtualenv
for each run. This is not yet a dependable execution design:

- Hardlinks are not an isolation boundary when an installer modifies an
  existing file in place.
- Copy-on-write cloning depends on filesystem support that the target VM has
  not guaranteed.
- Python virtualenvs commonly contain absolute interpreter paths and are not
  generally relocatable.
- Native wheels and shared libraries must match the Python interpreter, libc,
  architecture, and task-container image.
- A resolved package-name/version list is not a content identity for editable
  installs, dirty VCS trees, local wheels, or republished artifacts.
- Per-run cloning can become expensive once scientific environments reach
  several gigabytes and runs are frequent.

#### Recommendation

Use immutable environment generations:

1. An admin requests an install, uninstall, or upgrade through the existing
   environment experience.
2. The package manager creates a new generation out of place in the same
   compatible container/runtime environment.
3. It installs, validates, inventories, and content-hashes that generation.
4. On success, it atomically moves the environment's `current_generation_id`.
5. A run pins that generation. Existing runs never observe later installs.
6. Unreferenced generations are garbage-collected after a retention period.

For published reproducible execution, editable installs should be built into a
wheel or source snapshot. Merely marking the run non-reproducible is acceptable
for development, but not as the default production provenance story.

#### Closure criteria

- A feasibility test proves isolation during a concurrent package upgrade.
- The environment works inside the exact production task image.
- Native-extension and editable-install cases have explicit tests.
- Disk growth and generation garbage collection are measured.
- ADR 0028 records filesystem, interpreter, and ABI assumptions.

### G2-05: "The platform holds no data" is an unsafe governance statement

Severity: **High**

The platform is not a scientific data repository or long-term corpus. It still
stores data:

- Uploaded and fetched inputs during execution and retention.
- Generated outputs and packaged artifacts until TTL cleanup.
- Submitted parameters, logs, manifests, identities, sessions, and audit
  history beyond artifact expiry.
- References to institutional shared storage.

Transient storage changes retention obligations; it does not remove
confidentiality, authorization, residency, backup, or incident-response
questions while the bytes exist. A generic Python platform is also capable of
receiving identifiable data even if today's microbial workflows do not.

#### Recommendation

Replace the absolute statement with:

> BioPipeline2 is not a system of record. It processes explicitly permitted
> classes of transient input and output data, retains operational metadata for
> provenance, and deletes artifact bytes according to policy.

Then define:

- Permitted and prohibited data classes for v1.
- Whether human-identifiable or controlled data is technically prohibited or
  merely unsupported.
- Minimum infrastructure controls while transient bytes exist.
- Retention and redaction rules for parameters and logs, not only artifacts.
- A review trigger before a new publication may process a broader data class.

Disk encryption supplied by the VM or storage platform should be evaluated as
a low-cost baseline rather than rejected solely because BioPipeline2 is not a
corpus.

#### Closure criteria

- ADR 0001 is amended with precise data-handling language.
- Deployment documentation states allowed data classes.
- Log and parameter retention are defined separately from artifact TTL.
- The planned RNA-seq workload is classified before implementation.

### G2-06: The real deployment sample is not safe as a committed fixture

Severity: **High**

The repository tracks 2,536 files under `bio_pipeline_sample/`, approximately
175 MB in total. This includes `auth.sqlite`, `state.sqlite`, `installs.sqlite`,
run inputs and outputs, logs, local usernames and absolute paths. The auth
database contains five user records and 45 session records.

Password and session-token hashes, account identities, local paths, operational
history, and research files should not be treated as ordinary test fixtures.
Deleting them in a later commit would not remove them from Git history.

#### Recommendation

- Keep the original sample outside the application repository with restricted
  access and a recorded provenance owner.
- Build a sanitised, minimal regression corpus containing synthetic users,
  generated scientific inputs, representative YAML, and selected redacted task
  specifications.
- Preserve structural properties such as fan-out width, binding kinds, failure
  examples, and output shapes without preserving account or workstation data.
- If this repository has been shared, review and purge sensitive Git history.
- Invalidate source sessions and consider credential resets according to the
  exposure assessment.

#### Closure criteria

- No authentication database or live-derived session material is tracked.
- A secret and personal-data scan passes on the repository and its relevant
  history.
- Regression fixtures can be regenerated from documented scripts.
- The sanitised corpus still exercises every named acceptance archetype.

### G2-07: The feasibility corpus is too narrow and is being applied too late

Severity: **Blocker**

The roadmap's Phase 0 spike converts one growth-rate example, while Phase 1's
33-table schema is already described as largely complete. One example does not
exercise the design decisions most likely to invalidate the IR and schema.

The statement "all twelve pipelines and twelve job definitions" is not a
usable acceptance set. The sample actually contains 11 pipeline YAML files, 15
named graph definitions, eight unique graph names, 12 job-definition files, and
seven unique job names. Some files are duplicates or local variants, while
others contain several selectable graphs.

#### Recommendation

Create a canonical scenario matrix before freezing the compiler or API:

| Scenario | Required behaviour |
| --- | --- |
| Growth-rate family | Reusable graph components, variable matrix, typed whole-value substitution, `mapping_file` and `patterns` fan-out |
| FBA family | Two-stage dependencies, URL input, shared reusable download component, output hand-off |
| Collation family | Single-file versus folder fan-out and shared-storage delivery |
| Synthetic FBA family | Structured typed fields, string-to-number coercion, deterministic seeded execution |
| Published OD600 run | All three observed binding targets and saved values |

Each scenario needs expected compilation diagnostics, graph shape, task count,
selected callable arguments, outputs, and a scientific equivalence assertion.
Byte-for-byte comparison should be used only where outputs are deterministic;
otherwise compare agreed domain invariants.

#### Closure criteria

- ADR 0016 names the canonical scenarios and owners.
- Every legacy file is mapped to a scenario, declared duplicate, or explicitly
  excluded.
- The scenario matrix runs before the compiler and API contracts are frozen.
- Schema changes discovered by the spike are made before Phase 2 expansion.

### G2-08: Resource anti-starvation currently becomes head-of-line blocking

Severity: **Medium**

ADR 0029 prevents starvation by refusing to admit any task younger than the
oldest task that does not currently fit. If a large task waits behind a
day-long task, this can stop all smaller work for hours even when spare CPU and
memory are available. That conflicts with the stated goal that short tasks
should pack together and with the v1 requirement that heavy tasks not starve
short ones.

#### Recommendation

Define an aging or reservation policy rather than an immediate global barrier.
For example, allow bounded backfill until the waiting task reaches a maximum
age, then reserve capacity for it. Report both estimated queue position and the
reason a task is blocked. The policy should be load-tested with one running
large task, one waiting exclusive task, and a stream of short tasks.

#### Closure criteria

- The scheduling policy has an explicit fairness invariant.
- Tests cover large-task starvation and short-task head-of-line blocking.
- Queue-state explanations are available to the API and UI.

### G2-09: Trusted authors do not eliminate the need for cheap containment

Severity: **Medium**

ADR 0030 correctly distinguishes trusted admin-authored code from untrusted
researcher input. However, trusted authors can make mistakes, and packages from
PyPI, Git repositories, and editable working trees introduce supply-chain and
dependency risk. Trusting the author is not the same as trusting every
transitive package.

#### Recommendation

Keep inexpensive defence-in-depth defaults: non-root task user, no Docker
socket, no privileged mode, dropped capabilities, `no-new-privileges`, a
read-only root filesystem, explicit writable mounts, environment allowlisting,
resource limits, and Docker's default seccomp profile. These controls need not
pretend to be a hostile multi-tenant sandbox.

#### Closure criteria

- ADR 0030 distinguishes "not a hostile-code sandbox" from "no containment".
- The task-launch contract tests the baseline container restrictions.
- Package provenance and vulnerability-response responsibilities are assigned.

### G2-10: ADR 0013 is not the only decision that can block near-term work

Severity: **Medium**

The revised ledger calls shared-storage identity the single hard blocker. It is
the only blocker for implementing shared-storage access, but other open
decisions block different boundaries:

- ADR 0016 blocks meaningful acceptance criteria and the compiler fixture set.
- ADR 0023 can change the task contract if tasks need credentials.
- ADR 0003 must precede API contract freeze if MCP is in v1.
- ADR 0007 must precede final authentication and session UX.
- ADR 0014 affects event and notification architecture for day-long tasks.

#### Recommendation

Replace the single global blocker label with a decision-to-milestone matrix.
Development may proceed around an unresolved boundary, but the affected
contract cannot freeze until its decision is accepted or explicitly deferred.

## Decisions that should remain

The following parts of the revised plan are well supported and should be kept:

- PostgreSQL as the system of record and initial queue.
- Separate API, worker, scheduler, and janitor processes.
- Run, Task, and TaskAttempt as distinct lifecycle objects.
- Worker leases, heartbeats, expiry recovery, and idempotent submission.
- Idempotent schedule firing enforced by a database uniqueness constraint.
- Immutable executable revisions and versioned compiled IR.
- Compile-time rejection of unresolved references and nonexistent targets.
- Submit-time typed-value coercion with field-level errors.
- Explicit artifacts, deliveries, retention timestamps, and read auditing.
- Resource requests and admission control instead of a separate heavy-work
  queue.
- A generated OpenAPI contract shared by all external clients.

## Recommended gate before further implementation

Do not freeze the compiler, public API, or execution adapter until:

1. ADR 0026 is amended to preserve compile-time graph reuse.
2. `BindingPlan` and all observed binding targets are specified end to end.
3. ADR 0028 is replaced or supported by a successful environment-isolation
   feasibility test.
4. The canonical scenario matrix is accepted in ADR 0016 and exercised.
5. Active planning documents, code, tests, and READMEs describe the same domain
   and expression syntax.
6. The real deployment sample is removed from ordinary tracked fixtures and a
   sanitised regression corpus replaces it.

After those gates close, the walking skeleton remains the right next milestone.
