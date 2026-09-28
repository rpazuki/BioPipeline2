# Evaluation 1: Independent Review of the Implemented BioPipeline2

Date: 2026-09-25

Status: Review findings; no decisions in this document are accepted ADRs

Scope: The current BioPipeline2 implementation, migration documents, ADR queue,
tests, examples, deployment material, and the relationship between unresolved
decisions and code already written.

## Executive assessment

BioPipeline2 is a substantial and generally well-engineered prototype. It has a
clear domain/application/infrastructure/API separation, immutable executable
revisions, a compiled intermediate representation, explicit run and task
lifecycles, environment generations, typed values, publication bindings,
resumable uploads, artifacts, delivery, auditing, and separate operational
processes. The implementation is readable, strongly typed, and supported by a
large test suite.

It should not yet be accepted as complete or production-ready.

The most important reason is not missing polish. Two core guarantees are false
under real concurrency or authorization conditions:

1. Concurrent workers can jointly exceed the host resource budget.
2. Researchers can submit pipeline revisions directly and bypass the
   publication contract.

There is also an incorrect cancellation/lease-loss path that can turn a
cancelled task into a failure or allow an old worker to overwrite a task that a
new worker owns. In addition, several choices were recorded as accepted ADRs
under the project owner's name even though they were not actually ratified.

My overall judgement is therefore:

> Keep the implementation as a strong prototype, but freeze claims of
> completion and production deployment. Correct the execution and authorization
> defects, restore honest decision status, and validate the design against an
> agreed representative workflow set before expanding the feature surface.

## Where each finding stands

Added 2026-09-28, after the first response to this review. The findings
themselves are unedited; only these resolution notes and this table were
added, and each finding carries the same note in place.

| Finding | Severity | Status |
| --- | --- | --- |
| E1-01 Concurrent overcommit | Critical | **Fixed**, with the race reproduced as a test first |
| E1-02 Publication bypass | Critical | **Fixed**; direct submission is admin-only pending ADR 0022 |
| E1-03 Cancellation recorded as failure | High | **Fixed** |
| E1-04 Lost lease overwrites the new owner | High | **Fixed** |
| E1-05 ADRs accepted without approval | High governance | **Partly**: seven reclassified and enforced by a check; the decision review is the owner's |
| E1-06 Representative workflow set | High | **Open** -- needs ADR 0016 |
| E1-07 No CI | High release | **Open** -- needs a hosting platform |
| E1-08 Global shared-storage mounts | Medium/High | **Open** |
| E1-09 Shallow consistency checks | Medium | **Partly**: ADR status and counts enforced; phase status still prose |
| E1-10 Fixtures and deployment target | Medium | **Open** -- both halves need the owner |
| Spike waits after finishing | -- | **Fixed** |

The open rows are also carried in
[14-gap-closure-ledger.md](14-gap-closure-ledger.md) under "Still open from
evaluation 1", which is where this project tracks what is not done.

## How this evaluation was performed

The review used five complementary methods.

### 1. Decision and documentation audit

I compared:

- [`docs/adr/README.md`](docs/adr/README.md), which defines when an ADR may be
  marked accepted;
- every ADR's status and named decision owner;
- [`ASSUMPTIONS.md`](../ASSUMPTIONS.md);
- the open-question, feature-parity, roadmap, and gap-closure documents;
- the claims made by the root [`README.md`](../README.md).

This identified cases where an unresolved decision was implemented, where a
proposal was labelled as the project owner's accepted decision, and where
summary documents no longer matched the repository.

### 2. Static control-flow review

I traced the important paths end to end rather than reviewing individual files
in isolation:

- researcher submission -> publication binding -> run materialisation;
- worker claim -> lease -> container execution -> final task update;
- cancellation request -> heartbeat observation -> container stop -> run state;
- shared-root registration -> path validation -> worker mount;
- pipeline source -> compiler -> immutable revision -> task specification;
- environment install -> generation pin -> task-container mount.

This found authorization and lifecycle paths that are individually tested but
do not preserve the intended system-level invariant when connected together.

### 3. Automated verification

The following checks were run against the current repository:

| Check | Result |
| --- | --- |
| Backend lint and formatting | Passed |
| Strict backend mypy | Passed for 83 source files |
| Backend pytest suite | 896 passed; two dependency deprecation warnings |
| OpenAPI freshness | Passed |
| Alembic model/migration drift | No new operations detected |
| Frontend lint and formatting | Passed |
| Frontend TypeScript check | Passed |
| Frontend Vitest suite | 215 passed in 25 files |
| Generated frontend client freshness | Passed |
| Next.js production build | Passed, with an obsolete `eslint` configuration warning |

These results are meaningful evidence of implementation discipline. They are
not evidence that untested concurrency, end-to-end authorization, deployment,
or scientific-equivalence properties hold.

### 4. Targeted dynamic probes

For the admission-control claim, inspection alone was not treated as proof. I
created two queued tasks, each requesting the entire configured host budget,
and started two claims concurrently in two separate PostgreSQL sessions. A
barrier kept both transactions open until both calls had returned.

Both workers claimed a different full-budget task. The database therefore held
8,000 CPU millicores of claimed work against a configured total budget of 4,000.
The temporary tasks, runs, workers, pipelines, revisions, and users created for
this probe were removed afterwards.

I also ran the container spike. All six generated tasks reached `succeeded`.
However, `make spike` did not return promptly after the run was complete because
the bounded loop continued through exponential idle sleeps. I interrupted the
command after confirming the run and all six tasks had succeeded in PostgreSQL.

### 5. Coverage-to-claim comparison

I compared the assertions in the README and roadmap with what the tests
actually execute. In particular, I checked which sample pipelines are compiled,
what the Playwright suite covers, whether CI configuration exists, whether the
real science library is exercised, and whether the documented deployment
rehearsals have occurred.

## Findings and proposed solutions

## E1-01: Concurrent workers can overcommit the host

Severity: **Critical**

Resolution (2026-09-28): **Fixed** (`39117a2`). Admission is serialised by a
transaction-level advisory lock, *tried* rather than waited for so a claim
never blocks on a transaction it knows nothing about. The probe described above
is now a test: two claimers, two full-budget tasks, one claim
(`test_two_workers_cannot_jointly_overcommit_the_host`). It fails against the
previous code. A per-host budget row remains the right shape for a second
execution host, and is not built: `used` still sums every holding task
whichever host holds it, so the lock and the sum have to become per host
together.

### Problem

The claiming statement computes resource use in a `used` CTE and then locks one
eligible task with `FOR UPDATE SKIP LOCKED` in
[`backend/app/infrastructure/db/claiming.py`](../backend/app/infrastructure/db/claiming.py).

The aggregate budget itself is not represented by, or protected by, a shared
lock. Under PostgreSQL's normal statement snapshot semantics, two simultaneous
transactions can both observe the same pre-claim resource total. Because
`SKIP LOCKED` deliberately lets them lock different task rows, both can pass the
budget predicate and commit.

The existing concurrency test in
[`backend/tests/db/test_claiming.py`](../backend/tests/db/test_claiming.py)
checks that two sessions cannot claim the same task, but it calls the claimers
sequentially. It does not start two claims at the same time, and it does not use
two different tasks whose combined resources exceed the budget.

The operational documentation consequently makes a false guarantee when it
says multiple workers cannot oversubscribe a host.

### How it was found

The SQL comment claims that performing the budget check inside a transaction is
sufficient. That prompted a transaction-isolation review: a transaction gives
atomicity, but it does not serialize an aggregate predicate unless the
transactions contend on the same lock or run at a suitable serializable
isolation level with retry handling.

The two-session probe described above then reproduced the failure.

### Impact

- Two heavy jobs can start together and exhaust CPU or memory.
- The kernel or container runtime may kill tasks unpredictably.
- PostgreSQL, the API, and the operating system can lose the headroom the design
  says is reserved for them.
- An `exclusive` task is not reliably exclusive under simultaneous claims.

### Proposed solution

Represent the host budget as a row that every claim transaction must lock.

The preferred design is a `worker_hosts` or `execution_budgets` table with one
row per execution host. A claim transaction should:

1. `SELECT ... FOR UPDATE` the row for its host.
2. Calculate resources held by tasks assigned to that host.
3. Select and update one eligible task.
4. Commit, releasing the host-budget lock.

For the current one-host design, a transaction-level PostgreSQL advisory lock
with one documented key would also close the race, but a real row is easier to
inspect and extends naturally to multiple hosts. Merely raising transaction
isolation is less attractive because every serialization failure must then be
handled and retried correctly.

### Verification required

- Two simultaneous claims for two full-budget tasks result in exactly one
  claim.
- Several simultaneous small claims never exceed CPU, memory, task-count, or
  exclusive limits.
- The test must use separate committed sessions and a synchronization barrier.
- The deployment guide must not claim host-wide protection until this test
  passes.

## E1-02: Researchers can bypass the publication boundary

Severity: **Critical**

Resolution (2026-09-28): **Fixed** (`39117a2`). `POST /runs` is admin-only, and
such a run records `requested_from = 'admin'`, so a bypass is answerable from
the row. The researcher's route is the catalog. ADR 0022 is still open on
whether the endpoint should exist at all; until it is decided the narrower
answer stands. Not yet written: the regression test proving a field a
publication hides or fixes cannot be overridden through another endpoint.

### Problem

`POST /api/v1/runs` accepts `CurrentUser` and a raw `pipeline_revision_id` in
[`backend/app/api/v1/runs.py`](../backend/app/api/v1/runs.py). The API tests
explicitly assert that a researcher can use this endpoint.

The catalog has a separate submission path in
[`backend/app/api/v1/catalog.py`](../backend/app/api/v1/catalog.py). That path
loads the publication revision, validates visible fields, applies fixed and
submitted bindings, records the publication revision, and only then submits the
run. Direct `/runs` submission performs none of those publication checks.

This is not just an undocumented API convenience. It defeats the purpose of a
curated publication contract. It also implements an answer to
[`ADR 0022`](docs/adr/0022-ad-hoc-admin-submission-scope.md), which is still
`Proposed` and asks whether direct revision execution should exist for admins.
The implementation grants it to every researcher.

### How it was found

I compared the two submission entry points and followed both into
`submit_run`. The catalog path constructs a binding plan first; the generic run
path accepts the compiled pipeline's inputs directly. I then checked route
dependencies and tests to determine whether this was accidental. The test
`test_a_researcher_submits_a_run` confirms it is currently intentional.

### Impact

- A researcher can rerun an internal revision outside its publication policy.
- Publication-hidden inputs, fixed values, labels, and validation rules are no
  longer the sole researcher contract.
- A withdrawn or unpublished authoring revision may remain executable if its ID
  is known from prior run metadata.
- Compute governance is weakened because catalog curation can be bypassed.

### Proposed solution

Until ADR 0022 is decided:

- Make direct pipeline-revision submission admin-only.
- Keep researcher submission exclusively under
  `POST /catalog/{slug}/runs` or an equivalent publication-revision endpoint.
- Record a distinct trigger such as `manual_admin` for direct administrative
  runs.
- Consider requiring `publication_revision_id` for every non-admin-triggered
  run at the application and database boundary.

If direct researcher execution is later desired, it should be an explicit
product capability with its own authorization, visible contract, audit event,
resource policy, and accepted ADR. It should not be an accidental alternative
to publication.

### Verification required

- Anonymous and researcher calls to direct revision submission are refused.
- Admin direct submission works only if ADR 0022 accepts it.
- Researcher catalog submission still applies all binding and type rules.
- A regression test proves that a field hidden or fixed by a publication cannot
  be overridden through another endpoint.

## E1-03: Running-task cancellation is recorded as failure

Severity: **High**

Resolution (2026-09-28): **Fixed** (`39117a2`). A `StopSignal` carries the
reason from the worker -- the only component that knows it -- and a cancelled
container is recorded as a cancelled task and attempt. An ordinary non-zero
exit is still a failure; a timeout is still a timeout.

### Problem

The lease keeper observes `cancel_requested_at` and signals the cancellation
watcher. The watcher stops the container. However, the Docker adapter always
returns `cancelled=False`, and `execute_task` maps every non-timeout unsuccessful
outcome to `TaskStatus.FAILED` and `AttemptStatus.FAILED`.

The run aggregation rule prioritizes a failed task over cancellation. A user who
cancels a running task can therefore receive a failed run rather than a
cancelled run.

### How it was found

I traced the cancellation flag from `request_cancel`, through `LeaseKeeper` and
`_CancelWatcher`, into `DockerAdapter.run`, then followed the returned outcome
through `execute_task`, `_record`, and `advance_run`. A repository-wide search
also showed that no executor path records a running task as
`TaskStatus.CANCELLED`; only queued tasks are changed to cancelled directly by
SQL.

### Impact

- User-requested cancellation is reported as a scientific or infrastructure
  failure.
- Failure metrics and alerts become misleading.
- Retry and support decisions are made from the wrong terminal state.
- Audit history does not reflect what the user actually requested.

### Proposed solution

Carry an explicit stop reason from the worker into the execution result. At
minimum distinguish:

| Stop reason | Attempt result | Task result |
| --- | --- | --- |
| User cancellation | `cancelled` | `cancelled` |
| Wall-time limit | `timed_out` | `failed` or a dedicated timeout policy |
| Lease lost | Do not finalize from the old worker | Leave ownership to the reaper/new worker |
| Ordinary non-zero exit | `failed` | `failed` |

The adapter does not have to infer this from Docker's exit code. The worker
already owns the cancellation event and can pass the stop reason explicitly.

### Verification required

- Cancelling a genuinely running container produces cancelled task, attempt,
  and run states.
- A container that exits non-zero without cancellation remains failed.
- A cancellation racing with natural success follows one documented rule and
  is tested at the boundary.

## E1-04: A worker that lost its lease can overwrite the new owner

Severity: **High**

Resolution (2026-09-28): **Fixed** (`39117a2`). Every worker-owned finalisation
is a compare-and-set on `claimed_by` *and* `attempt_count`. A worker that
changes no rows writes nothing further: no task status, no dependants released,
no run advanced. A lease-lost attempt returns before promotion, so its outputs
cannot become the winning result.

### Problem

When lease renewal returns no row, the old worker correctly concludes that the
task is no longer its own and stops its container. After the container returns,
however, `_record` updates `run_tasks` using only `WHERE id = :i`. It does not
check `claimed_by`, the attempt number, or the expected current status.

If the reaper has requeued the task and another worker has claimed it, the old
worker can mark the task failed and clear the new worker's lease.

### How it was found

This appeared while tracing E1-03. The lease keeper comment says the old worker
must stop rather than race the new owner, so I checked whether the final write
was compare-and-set against ownership. It is not. Existing tests prove that the
lease keeper raises the signal, but do not continue through container return and
final recording after another worker has claimed the task.

### Impact

- A valid new attempt can be corrupted by the previous attempt.
- Two workers may execute the same task while the database reports neither
  ownership correctly.
- The task can become terminal while the replacement container is still
  running.
- Attempts, artifacts, and task status can disagree.

### Proposed solution

Every worker-owned finalization must be a compare-and-set operation:

```sql
UPDATE run_tasks
SET ...
WHERE id = :task_id
  AND claimed_by = :worker_id
  AND attempt_count = :attempt
  AND status IN ('claimed', 'running')
```

The worker must verify that exactly one row changed. If zero rows changed, it no
longer owns the task and must not write task status, release dependants, advance
the run, or promote outputs. Its attempt can be marked lost only under a rule
that cannot overwrite the replacement attempt.

### Verification required

- Reclaim and reassign a task while the old executor is still returning.
- Assert that the old worker changes zero task rows.
- Assert that only the new worker can finalize the task and release dependants.
- Assert that artifacts from a lease-lost attempt cannot be promoted as the
  winning result.

## E1-05: Some ADRs were accepted without demonstrated owner approval

Severity: **High governance risk**

Resolution (2026-09-28): **Partly addressed; the decision review is the
owner's**. The seven records named here are now `Implemented proposal - pending
ratification`, each stating what is already built on it, and
`check_consistency.py` fails when an ADR's status disagrees with the index
section listing it. The remaining fifteen `Accepted` records have no recorded
approval event either; they were left as they are rather than unmarking
decisions that may have been made in conversation. Ratifying or reclassifying
them is the outstanding half.

### Problem

The ADR workflow states that an ADR becomes accepted once the project owner
agrees. Several records are nevertheless marked `Accepted` and name Roozbeh
Pazuki as decision owner even though the current clarification is that some
blockers were not decided.

The clearest records requiring a ratification audit are:

| ADR | Decision already embedded in code |
| --- | --- |
| 0013 | Service-account shared-storage identity with human attestation |
| 0015 | RRULE plus intervals, DST policies, and catch-up semantics |
| 0031 | Publication-owned immutable binding plans |
| 0032 | One container per stage-task |
| 0033 | HTTP chunking for smaller files and shared storage for very large files |
| 0034 | Types declared in pipeline documents rather than a registry |

ADR 0008 should also be rechecked because it chooses generic Ubuntu-oriented
Docker deployment over the Red Hat environment expected in the original
request.

These are mostly defensible engineering proposals. The defect is representing
them as the owner's accepted choices, not the fact that the agent developed a
recommendation and implemented it.

### How it was found

I compared the ADR status table, each ADR header, the documented acceptance
workflow, Git history, and the open questions. I also checked whether code and
documentation had already hardened around each decision.

### Impact

- Later work treats reversible proposals as settled constraints.
- The project owner appears accountable for decisions they did not make.
- Alternatives become progressively more expensive to select.
- The gap ledger can report closure without actual governance closure.

### Proposed solution

Introduce a status that tells the truth about the current state, for example:

- `Proposed`
- `Implemented proposal - pending ratification`
- `Accepted`
- `Superseded`
- `Deferred`

Separate `Author` from `Decision owner` and `Approved by`. Reclassify every ADR
without an identifiable approval event, then conduct a short decision review.
Keeping the implementation while a decision is pending is acceptable when the
cost to reverse is recorded and contract freeze is prohibited.

### Verification required

- Every accepted ADR has an approval date and approver.
- The ADR index is generated or checked against file headers.
- No open or pending ADR is described as decided in README, roadmap, or code
  comments.
- The owner reviews the decisions with high reversal cost before further API or
  schema freezing.

## E1-06: The representative-workflow gate was bypassed

Severity: **High**

Resolution (2026-09-28): **Open**. Unchanged: one converted pipeline, ADR 0016
unanswered. Nothing here can proceed without the named workflow set.

### Problem

[`ADR 0016`](docs/adr/0016-representative-workflow-set.md) remains proposed.
[`gap2.md`](gap2.md) required a canonical scenario matrix before freezing the
compiler, API, or execution adapter. The implementation instead built deeply
around one converted growth-rate pipeline.

`backend/tests/domain/test_examples.py` only scans `examples/pipelines`, which
currently contains one YAML file. The container spike uses the same family and
a standard-library stand-in for `labUtils`. Its own README correctly says it
does not prove the real library or scientific equivalence.

The following plan-critical shapes remain unproved as complete scenarios:

- FBA dependencies, URL acquisition, reusable download logic, and output
  hand-off;
- collation with single-file and folder fan-out;
- synthetic FBA structured fields and deterministic scientific assertions;
- all observed publication binding target kinds and saved values;
- real `labUtils`, native dependencies, and expected scientific outputs.

### How it was found

I compared the closure criteria in `gap2.md`, ADR 0016, the files selected by
the example test, the spike documentation, and the real YAML/job-definition
families retained from the sample. The test suite's size initially suggests
broad coverage, but the canonical pipeline corpus is only one converted
pipeline.

### Impact

- The compiler and schema may be optimized around one workflow family.
- Unsupported shapes will be discovered after API and persistence contracts
  are expensive to change.
- Green tests can coexist with failure to express or execute a real required
  pipeline.
- The README's statement that only operational breadth is missing is not
  justified.

### Proposed solution

Decide ADR 0016 and build the canonical matrix requested in `gap2.md`. For each
scenario, record:

| Required evidence | Meaning |
| --- | --- |
| Source mapping | Which legacy files it represents or intentionally excludes |
| Compile expectation | Diagnostics, graph shape, references, and component pins |
| Materialisation expectation | Task count, dependencies, fan-out keys, and arguments |
| Execution expectation | Required packages, resource class, files, and deliveries |
| Scientific assertion | Golden output, tolerance, invariant, or expert-reviewed result |
| Ownership | Who can confirm the scenario represents real use |

Use sanitized inputs and a controlled build of the real science package. Where
the old output is nondeterministic, compare domain invariants rather than bytes.

### Verification required

- Every retained legacy pipeline/job file maps to a scenario, duplicate, or
  explicit exclusion.
- Every accepted scenario compiles and materializes in CI.
- At least one controlled end-to-end run per family executes against the real
  package.
- Scientific-equivalence checks are reviewed by a domain owner.

## E1-07: CI and end-to-end validation do not support the completion claim

Severity: **High release risk**

Resolution (2026-09-28): **Open**. No CI exists. The repository has no
configured remote, so the hosting platform is undecided; the gates themselves
are already commands (`make check`, `make ui-check`, the container suite, `make
spike`).

### Problem

There is no checked-in GitHub, GitLab, Jenkins, or equivalent CI pipeline. The
local `make check` target runs backend checks only. `make ui-check` omits the
Next.js production build and Playwright. Container tests, the spike, image
builds, vulnerability scanning, restore rehearsal, and clean-VM deployment are
not enforced by CI.

The Playwright file explicitly says it does not cover submit -> execute ->
monitor -> download or large-upload behavior. Phase 9 documentation also admits
that clean installation, restore, and long-running upgrade rehearsals have not
been performed.

The production build currently passes but warns that `eslint` is no longer a
recognized Next.js configuration key.

### How it was found

I enumerated CI configuration files, inspected `Makefile` targets, read the
Playwright test, ran both check suites and the production build, and compared
their actual commands with the CI requirements in
[`12-testing-ci-and-release.md`](12-testing-ci-and-release.md).

### Impact

- Tests can pass locally but be skipped entirely before merge.
- A stale image, broken production build, or migration issue can reach release.
- The documented deployment path remains a hypothesis.
- Regression protection depends on a person remembering several separate
  commands and infrastructure prerequisites.

### Proposed solution

Create CI for the repository's actual hosting platform with these gates:

1. Backend lint, formatting, strict typing, unit tests, and PostgreSQL tests.
2. Alembic upgrade and model-drift checks against a fresh database.
3. OpenAPI regeneration and generated TypeScript client freshness.
4. Frontend lint, formatting, type check, unit tests, and production build.
5. Container image builds and real execution-adapter tests.
6. Canonical pipeline compilation and materialisation.
7. A composed end-to-end path from publication through artifact download.
8. Documentation links, ADR metadata, terminology, and fixture safety checks.

Nightly or release workflows should add a restore rehearsal, vulnerability
scan, and complete representative workflow execution.

### Verification required

- A clean clone passes CI without local state.
- Removing a migration, generated client change, or required output causes the
  expected job to fail.
- The release commit has a recorded end-to-end result.
- The warning in `next.config.mjs` is removed.

## E1-08: Shared-storage mounts are global rather than project-scoped

Severity: **Medium now; High if projects are enabled**

Resolution (2026-09-28): **Open**. Unchanged. The mount set is still global and
still cached at worker startup.

### Problem

`shared_root_mounts` selects every active readable attested root. The worker
loads that global set once at startup and places all of it in every task
container. Neither query is scoped to the run's `project_id`.

The current API creates everything in one default project, so this is not an
immediate cross-project vulnerability under the accepted single-project v1
assumption. It is nevertheless a dangerous latent boundary because the schema,
comments, and ADR claim project isolation is preserved.

The once-at-startup cache also means root revocation or addition does not affect
an existing worker until it restarts.

### How it was found

I followed root registration into the mount query and then searched every call
site of `shared_root_mounts`. The only production call populates a singleton
adapter during worker construction; no run or project identifier is available
at that point.

### Impact

- Enabling multiple projects without redesign exposes all project roots to all
  task code.
- Revoked roots may remain mounted by long-lived workers.
- The documentation describes a security boundary the implementation does not
  enforce.

### Proposed solution

Resolve mounts for each claimed task using the run's project ID. Pass an
immutable per-execution mount map to `DockerAdapter.build_command` instead of
mutating a worker-global adapter map.

While v1 remains single-project, add a deployment assertion that exactly one
active project exists and document that project columns are structural only.
Before multi-project activation, require project-scoped authorization tests and
remove that assertion deliberately.

### Verification required

- A task in project A cannot see or select project B's root.
- Revocation prevents the next task from receiving the mount without a worker
  restart.
- Root selection, fan-out validation, mounting, and delivery all use the same
  project-scoped policy.

## E1-09: Documentation consistency checks give false confidence

Severity: **Medium**

Resolution (2026-09-28): **Partly addressed**. The ADR half is enforced:
statuses, index sections, and the counted summary sentence are checked, and the
stale counts in `README.md` and `ASSUMPTIONS.md` were corrected along with the
roadmap's claim that ADR 0013 was unresolved and unbuilt. The test count is
gone from the README rather than maintained by hand. Roadmap phase status and
acceptance evidence are still prose.

### Problem

The repository's consistency script passes while active documents still
disagree. Examples include:

- the migration README reports obsolete answered/open-question counts;
- the root README advertises an obsolete test count;
- the roadmap calls shared-storage identity unresolved and unbuilt after the
  ADR and implementation claim it is accepted;
- phase status text does not consistently reflect what is built or still
  unverified;
- the root README says missing work is chiefly Phase 9 even though ADR 0016,
  full end-to-end acceptance, URL input, and several scope decisions remain
  open.

### How it was found

I compared generated facts from the repository with prose claims, then ran the
existing consistency command. Because the command passed, its checks are too
shallow to enforce the source-of-truth order required by `gap2.md`.

### Impact

- A new contributor cannot tell whether a statement is current.
- Open decisions can disappear behind optimistic summaries.
- Test and table counts become decorative rather than trustworthy.
- Reviewers may accept a phase based on prose rather than its acceptance
  evidence.

### Proposed solution

Move volatile facts into machine-readable metadata and generate summaries from
them. At minimum, consistency checks should parse and compare:

- ADR headers and the ADR index;
- roadmap phase status and acceptance evidence;
- actual test counts only if counts remain documented;
- schema/model table counts;
- open blockers referenced by `ASSUMPTIONS.md` and README;
- forbidden superseded terminology and links.

Avoid exact test counts in README unless generated automatically. A statement
such as "run `make check`" ages better than a manually maintained number.

### Verification required

- Changing an ADR header without updating the index fails the check.
- Calling a proposed ADR accepted in another active document fails the check.
- Broken local links and duplicate document-map entries fail the check.
- The root status summary lists every open contract or acceptance blocker.

## E1-10: Live-derived fixtures and deployment target need explicit decisions

Severity: **Medium**

Resolution (2026-09-28): **Open; both halves need the owner**. The tracked
fixtures are unchanged, and removing them from the tree would not remove them
from history. ADR 0008 (Ubuntu over Red Hat) is now marked pending
ratification, which makes the question visible but does not answer it.

### Problem

The full `bio_pipeline_sample` directory is now ignored, which is correct, but
24 YAML and job-definition files copied from the deployment remain tracked.
They include personal/lab labels and institutional Windows share paths. The
ignore rule does not remove files already committed to Git history.

Separately, the operational guide is written for Ubuntu 24.04 using `apt`, while
the expected environment described by the project owner is normally a Red Hat
Linux VM. ADR 0008 chose a generic Linux/Docker target and removed Red Hat,
Podman, and SELinux specifics. That may be a valid choice, but it needs actual
owner and infrastructure approval.

### How it was found

I compared `git ls-files` with `.gitignore`, searched retained fixtures for
identity and absolute-path material, and compared the deployment guide with the
original target environment and ADR 0008.

### Impact

- Live-derived metadata may be distributed more widely than intended.
- Deleting it from the current tree would not remove prior Git history.
- Ubuntu-only instructions may fail or produce an insecure workaround on the
  actual VM, particularly around package installation, SELinux, mounts, and the
  container runtime.

### Proposed solution

Perform a fixture exposure review before deleting or rewriting history. Replace
tracked live-derived files with a documented sanitized corpus that preserves
graph shape, fan-out, binding kinds, and failure examples without preserving
names or institutional paths.

Ratify the production OS/runtime choice. If Red Hat remains the target, add and
rehearse Red Hat-specific installation, SELinux, systemd, container-runtime,
volume-mount, and shared-storage instructions. If Ubuntu is deliberately chosen
instead, record why and update the stated deployment assumptions.

### Verification required

- A secret and personal-data scan passes on the current tree and relevant
  history.
- Every regression fixture has a synthetic or sanitized provenance statement.
- Installation is executed from the documentation on the selected production
  OS.
- A real task can access its permitted shared root and cannot access any other
  root under the selected security configuration.

## Additional validation issue: the spike finishes work but waits excessively

`scripts/dev/spike.py` calls `Worker.run_forever` with a fixed iteration count.
After all six tasks complete, the remaining iterations are idle. Worker idle
backoff grows to 30 seconds, so the command can spend roughly eleven minutes
waiting after it has already proved its result.

This is not a platform correctness defect, but it makes an important validation
tool appear hung and discourages routine use.

The spike should instead stop when its target run is terminal and no target task
is still claimable, with a wall-clock deadline as the safety bound. It should
also clean or explicitly retain its generated database and disk fixtures.

Resolution (2026-09-28): **Fixed** (`39117a2`). `scripts/dev/spike.py` drains
until its run reaches a terminal status, bounded by a wall-clock deadline, and
returns as soon as the work is done. Its database and disk fixtures are still
left behind deliberately and still undocumented as such.

## What should be retained

The findings above do not justify discarding the implementation. The following
work is strong and should remain unless a ratified decision directly changes it:

- PostgreSQL as the system of record and initial queue;
- immutable pipeline, publication, and environment snapshots;
- the compiled intermediate representation and located diagnostics;
- compile-time reference and binding validation;
- stage-level execution for live Python object flow;
- explicit Run, Task, and TaskAttempt lifecycles;
- leases, heartbeats, and a separate reaper process;
- separate scheduler and courier processes;
- task containers with inexpensive containment defaults;
- typed-value coercion before execution;
- resumable bounded-memory uploads;
- explicit artifacts, retention, delivery, and read auditing;
- generated OpenAPI types for the frontend;
- the environment-generation approach rather than per-run mutable clones;
- the existing unit, database, API, and frontend test coverage.

## Recommended steps

The following order is deliberate. It fixes incorrect guarantees before adding
features, and obtains owner decisions before more contracts harden around them.

### Step 1: Freeze release claims and decision status

Do not deploy this build as production and do not add major features yet.
Reclassify unratified accepted ADRs as `Implemented proposal - pending
ratification`. Correct the README so it describes a prototype undergoing
acceptance rather than a system missing only operational hardening.

Exit condition: the ADR index, open-question list, assumptions, roadmap, and
README agree on what is decided, proposed, implemented, and verified.

### Step 2: Correct the two critical defects

Serialize admission through a host-budget lock and make direct revision
submission admin-only pending ADR 0022. Add the real concurrent budget test and
the publication-bypass authorization test before changing any other behavior.

Exit condition: simultaneous full-budget claims cannot overcommit, and a
researcher cannot execute a pipeline except through an authorized publication.

### Step 3: Repair cancellation and lease ownership

Introduce explicit stop reasons, record running cancellation as cancellation,
and make every final worker write conditional on worker ID plus attempt number.
Ensure a lease-lost attempt cannot promote outputs or advance the run.

Exit condition: end-to-end tests cover user cancellation, timeout, worker loss,
reclaim, reassignment, and the old-worker/new-worker race.

### Step 4: Conduct a focused decision review

Review ADRs 0008, 0013, 0015, 0022, 0023, and 0031-0034 with the project owner.
Also decide or explicitly defer AI, MCP, CLI/notebook support, SSO,
notifications, in-app backup, URL inputs, and the acceptance workflow set.

For each decision, record the rationale, consequences, approver, approval date,
and cost to reverse. An implemented recommendation can be accepted unchanged;
the important correction is making that acceptance real.

Exit condition: every contract-affecting blocker is accepted or explicitly
deferred, and no code relies silently on an open answer.

### Step 5: Build and execute the canonical scenario matrix

Accept ADR 0016, sanitize the fixtures, map every legacy definition, and run the
growth-rate, FBA, collation, synthetic FBA, and publication-binding scenarios.
Use the real controlled science environment and domain-reviewed expected
results where available.

Exit condition: every required workflow family compiles, materializes, runs,
and satisfies its agreed scientific or structural assertions.

### Step 6: Close storage and data-governance boundaries

Make shared mounts run/project-scoped, review retained live-derived fixtures,
decide permitted data classes, and define retention for parameters, logs, audit
events, uploads, workspaces, and outputs. Reassess task secrets before any
workflow needs credentials.

Exit condition: storage access and retention are enforceable policies rather
than attestations or prose alone, and fixture/history exposure has a recorded
resolution.

### Step 7: Establish mandatory CI and release evidence

Implement the CI gates described in E1-07. Make the canonical corpus and true
concurrency tests mandatory. Add composed Playwright coverage for authoring,
publication, researcher submission, execution, cancellation, monitoring, and
artifact retrieval.

Exit condition: a clean clone produces images and passes all required checks in
automation, and a deliberately introduced contract or migration drift causes a
failing job.

### Step 8: Rehearse the actual production environment

Choose the supported Linux/runtime combination, then perform a clean install,
backup/restore, storage reconciliation, upgrade with a long-running task,
worker drain, rollback, and failure-alert exercise on a production-shaped VM.

Exit condition: the runbooks have been followed successfully by someone other
than their author on the selected operating system.

### Step 9: Re-evaluate v1 readiness

Repeat an independent review after Steps 1-8. At that point, assess remaining
scope separately from correctness. Features explicitly deferred by accepted
decisions do not block v1; false authorization, execution, provenance, or
recovery guarantees do.

Exit condition: all critical/high findings are closed or consciously accepted
with an owner, representative workflows pass, release rehearsals pass, and the
documentation accurately states the remaining limitations.
