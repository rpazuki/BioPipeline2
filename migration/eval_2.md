# Evaluation 2: Review of the Response to Evaluation 1

Date: 2026-10-01

Status: Review findings and recommendations; this document does not accept any
ADR or make a product decision for the project owner

Reviewed revision: `76b74f5` (`docs: record where each evaluation-1 finding
stands`), including the implementation changes in `39117a2`

## Executive assessment

The response to Evaluation 1 is serious work. The admission-control race and
researcher publication bypass have credible fixes. Cancellation now carries an
explicit reason, the task finalization update is guarded by worker and attempt
ownership, and seven unapproved ADRs are no longer represented as owner
decisions. These changes materially improve the prototype.

The response nevertheless closes more than it has proved. In particular,
E1-04 is only partly fixed: task status is protected, but output promotion and
attempt finalization still happen outside that protection. E1-03 has a sensible
implementation but not the end-to-end evidence required by Evaluation 1. The
new documentation also repeats the premature closure and contains ADR-status
contradictions that the expanded consistency checker does not detect.

My revised judgement is:

> Accept E1-01 and E1-02 as implemented fixes for the current single-host
> design. Treat E1-03 as implemented but awaiting end-to-end verification, and
> E1-04 as only partially fixed. Correct the status documents before relying on
> them for release readiness.

## Status after this review

| Earlier finding | Evaluation 2 judgement |
| --- | --- |
| E1-01: concurrent host overcommit | **Fixed for the current single-host budget model** |
| E1-02: publication bypass | **Fixed**, with ADR 0022 still open on whether admin direct submission remains |
| E1-03: cancellation recorded as failure | **Implemented; end-to-end verification incomplete** |
| E1-04: old worker overwrites new owner | **Partly fixed; output and attempt races remain** |
| E1-05: unapproved ADRs | **Partly addressed; owner ratification remains** |
| E1-06 through E1-08 and E1-10 | **Still open as recorded in Evaluation 1** |
| E1-09: documentation consistency | **Partly addressed; current contradictions demonstrate the remaining gap** |

## Where each finding stands

Added 2026-10-01, after the response to this review. The findings are
unedited; only these resolution notes and this table were added, and each
finding carries the same note in place.

| Finding | Severity | Status |
| --- | --- | --- |
| E2-01 Promotion outside ownership | High | **Fixed** -- ownership is held from before promotion to the commit |
| E2-02 Terminal attempt rewritten | High provenance | **Fixed** -- attempt completion is a compare-and-set |
| E2-03 Cancellation unverified | Medium verification | **Fixed** -- tested through the real path; the precedence rule was missing and is now implemented |
| E2-04 Status documents disagree | Medium governance | **Partly** -- the contradictions are corrected and prose is checked against ADR status; no canonical status file |
| Step 4: run the database-backed suite | -- | **Done** -- Docker and PostgreSQL started, full suite run, no tests skipped |

The still-open Evaluation 1 items (E1-06 through E1-08, E1-10, the owner's
decision review, and the structural half of E1-09) are unchanged and are
tracked in [14-gap-closure-ledger.md](14-gap-closure-ledger.md).

## How this review was performed

I read the two response commits, compared their code and documentation changes
with every verification condition in `eval_1.md`, and retraced these paths:

- concurrent claim -> admission lock -> claim commit;
- direct run submission -> authorization -> recorded trigger;
- cancellation/lease loss -> container stop -> attempt/task/run finalization;
- successful container exit -> output collection -> artifact promotion -> task
  compare-and-set -> transaction commit;
- reaper lease recovery -> lost attempt -> old-worker return;
- ADR file status -> ADR index -> root README -> gap-closure ledger.

I also ran the available checks. Frontend lint, formatting, TypeScript, 215
Vitest tests, and generated-client freshness passed. Backend lint, formatting,
mypy, documentation consistency, OpenAPI freshness, and 402 tests that did not
need PostgreSQL passed. The remaining 502 tests were skipped because PostgreSQL
was unavailable; `make check` then failed at Alembic connectivity. The database
could not be started because the local Docker daemon was not running. Therefore
the database-backed fixes were reviewed statically in this pass rather than
independently re-executed.

## E2-01: Output promotion is not protected by task ownership

Severity: **High**

Resolution (2026-10-01): **Fixed**. Ownership is now taken with `SELECT ... FOR
UPDATE` immediately before promotion and held until the commit, so artifacts,
manifests, deliveries, the attempt and the task are written on one side of a
boundary the reaper cannot cross. Collection and checksums stay outside the
lock, which is where the time goes. The byte-store policy is unchanged and is
the one this finding recommends: attempt-scoped bytes first, rows only once
ownership is held, unreferenced bytes left for reconciliation. Proved by
`test_a_task_taken_away_mid_flight_leaves_no_artifacts`, which takes the task
away in the window between the container returning and the outputs being kept,
and asserts zero artifacts and zero deliveries; it fails against the previous
code.

Related earlier finding: E1-04

### Problem

The new task update is correctly conditional on all of the following:

- task ID;
- `claimed_by` worker ID;
- `attempt_count`;
- task status being `claimed` or `running`.

That protects the task row from an old worker's final verdict. It does not
protect the operations that occur before that update.

After the container returns, `execute_task` checks `stop.lost` once. It then
collects outputs and calls `promote_outputs`. Promotion writes bytes to the
artifact store, inserts artifact and manifest records, and plans delivery rows.
Only after those side effects does `_record` attempt the guarded task update.

The remaining race is:

1. Worker A's container returns successfully and `stop.lost` is still false.
2. Worker A begins collecting or promoting outputs.
3. Its lease expires; the reaper requeues the task and Worker B claims it.
4. Worker A creates output artifacts and deliveries for its old attempt.
5. Worker A's guarded task update changes zero rows, correctly detecting that
   Worker B owns the task.
6. `Worker.execute` nevertheless commits the session. The losing output rows
   remain recorded even though the task verdict was rejected.

The attempt-specific storage key prevents Worker A from overwriting Worker B's
bytes, but it does not make Worker A's artifact and delivery records a valid
winning result. A delivery can expose an output from an attempt whose task was
later completed by somebody else.

### How it was found

I followed the order of operations rather than stopping at the new
compare-and-set:

- `backend/app/workers/executor.py`: the lease-loss check is before output
  collection;
- the same file calls `promote_outputs` before `_record`;
- `backend/app/application/artifacts.py` writes bytes, artifacts, manifests,
  and deliveries during promotion;
- `_record` performs the ownership compare-and-set only afterwards;
- `backend/app/workers/worker.py` commits even when `outcome.owned` is false.

The new ownership test asserts that the successor's task row is unchanged. It
does not give the old attempt declared outputs or assert that zero artifacts
and deliveries were created. It therefore cannot detect this race.

### Impact

- A losing attempt can leave downloadable output artifacts.
- Delivery work can be planned for output that was never accepted as the task
  result.
- Artifact history, attempt history, and final task state can disagree.
- Retention and storage accounting include data that should have remained
  unpromoted attempt scratch data.
- The statement that lease-lost outputs cannot become a winning result is
  stronger than the implementation.

### Recommended solution

Use one ownership-guarded finalization transaction:

1. Collect and validate output files before taking a database row lock. This
   keeps checksums and other potentially expensive inspection outside the
   critical section.
2. Immediately before promotion, lock the task row with `SELECT ... FOR UPDATE`
   and verify `claimed_by`, `attempt_count`, and status.
3. If ownership is gone, roll back and return a lost outcome without creating
   artifact, manifest, or delivery rows.
4. While holding the task-row lock, register promoted artifacts and deliveries,
   close the attempt, and make the task terminal in the same transaction.
5. Commit once. The reaper may wait briefly on the task row, but it cannot
   transfer ownership halfway through finalization.

The byte-store operation needs an explicit policy because PostgreSQL cannot
roll back filesystem writes. The existing safe ordering can remain: write
attempt-scoped bytes first, then create database rows while ownership is
locked. If ownership or the database transaction fails, leave the unreferenced
bytes for reconciliation. Do not create artifact or delivery rows before
ownership is established.

An alternative is a guarded transition to a dedicated `finalizing` state, but
that expands the lifecycle and reaper rules. A short task-row lock is simpler
for the present one-VM design.

### Verification required

- Pause Worker A after output collection and before promotion.
- Expire and reclaim its lease, then let Worker B claim the task.
- Resume Worker A.
- Assert that Worker A creates no task-output artifact, manifest, or delivery
  row.
- Assert that Worker A does not release dependants or advance the run.
- Assert that only Worker B can publish the accepted outputs.
- Repeat with the same worker ID reclaiming a later attempt, proving that
  `attempt_count`, not worker ID alone, protects finalization.

## E2-02: A terminal lost attempt can be rewritten by the old worker

Severity: **High provenance risk**

Resolution (2026-10-01): **Fixed**. Attempt completion is a compare-and-set on
`status = 'running' AND finished_at IS NULL`. A worker that finds the row
already terminal leaves the account that is there and logs it; `_abandon` goes
through the same path, so closing a lost attempt as lost is idempotent rather
than accidentally harmless.
`test_a_lost_attempt_keeps_the_reapers_account_of_it` has the reaper close the
attempt while the worker is returning, and asserts the reaper's record
survives. Not done: a database constraint forbidding terminal-to-terminal
attempt transitions. The guard is in the one statement that writes them, not in
the schema.

Related earlier finding: E1-04

### Problem

The reaper closes an abandoned running attempt as `lost`. The old worker may
then return without observing the lease-loss signal in time and enter `_record`.
`_record` updates `run_task_attempts` by attempt ID only, before checking task
ownership. It can therefore change the already-terminal attempt from `lost` to
`succeeded`, `failed`, `cancelled`, or `timed_out`.

The comment that an attempt row is "always safe to close" is not correct once
the reaper is also an authorized finalizer. The attempt belongs historically to
Worker A, but Worker A no longer has exclusive authority to decide its terminal
state after the reaper has recorded lease loss.

`_abandon` has the same unconditional update shape. Rewriting `lost` to `lost`
is normally harmless, but terminal attempt transitions should still be
idempotent and guarded rather than relying on the values happening to match.

### How it was found

I compared `_record` and `_abandon` with `close_lost_attempts` in the reaper and
with the attempt state machine. The state machine declares `lost`, `succeeded`,
`failed`, `cancelled`, and `timed_out` terminal, but the SQL update does not
enforce terminal immutability. The new successor-owner test checks only the
task's status and owner; it does not assert the first attempt's final state.

### Impact

- Audit history can say an expired attempt succeeded after the reaper recorded
  that it was lost.
- The attempt result can reference outputs that were not accepted by the task.
- Operational metrics for lost workers, failures, and successful attempts can
  be wrong.
- A terminal state machine exists in documentation and Python but is not
  preserved at the write boundary.

### Recommended solution

Make attempt completion a compare-and-set:

```sql
UPDATE run_task_attempts
SET status = :status,
    exit_code = :exit_code,
    finished_at = now(),
    result = :result
WHERE id = :attempt_id
  AND status = 'running'
  AND finished_at IS NULL
RETURNING id
```

If no row is returned, read the existing attempt status. Treat an existing
`lost` status as authoritative and return `owned=False`; do not overwrite its
result. Unexpected terminal states should be logged as invariant violations.

Perform this guarded attempt update inside the same ownership-locked transaction
recommended in E2-01. This produces one coherent decision about the task,
attempt, artifacts, deliveries, dependants, and run.

### Verification required

- Let the reaper mark attempt 1 `lost` and Worker B claim attempt 2.
- Let Worker A report success, failure, timeout, and cancellation in separate
  cases.
- Assert that attempt 1 remains `lost`, including its original finish time and
  result.
- Assert that attempt 2 and the task remain untouched by Worker A.
- Add a database constraint or repository test demonstrating that no terminal
  attempt can transition to another terminal state.

## E2-03: Cancellation is implemented but not verified end to end

Severity: **Medium verification risk**

Resolution (2026-10-01): **Fixed, including a rule the implementation did not
have**. Two tests now run through the real orchestration:
`test_cancelling_a_running_task_cancels_the_task_and_the_run` drives
`request_cancel`, the heartbeat that observes it, the watcher that stops a
genuinely blocked container, the executor, and `advance_run`, asserting a
cancelled attempt, task and run;
`test_work_already_finished_is_not_undone_by_a_cancellation` encodes the
precedence rule. Writing that test found the implementation on the wrong side
of it: the executor checked the stop signal before the outcome, so a container
that had already succeeded was recorded as cancelled. Success now wins, the
rule is written down in `app/workers/stopping.py`, and the run-level
cancellation still stops everything that had not started. The API layer itself
is not in the test -- the handler calls `request_cancel` and nothing else.

Related earlier finding: E1-03

### Problem

`StopSignal` is a good correction. It places the distinction between user
cancellation and lease loss in the worker, which is the component that knows
why it stopped the container. The executor also maps user cancellation to
cancelled task and attempt states instead of treating exit code 137 as failure.

The added tests do not, however, execute the path that originally failed. They
raise `StopSignal(CANCELLED)` before calling `execute_task` and use a fake
adapter that immediately returns a nonzero result. This verifies executor
mapping, but not:

- the API cancellation request;
- `LeaseKeeper` observing `cancel_requested_at`;
- `_CancelWatcher` stopping a genuinely running container;
- the worker recording the task and attempt;
- `advance_run` producing a cancelled run;
- cancellation racing with natural successful completion.

Evaluation 1 explicitly required those boundary behaviours. Calling E1-03
fully fixed conflates implementation with acceptance evidence.

### Recommended solution

Keep the current `StopSignal` design and add two composed tests:

1. Start a controllable long-running adapter/container, request run
   cancellation through the application/API, wait for the heartbeat path, and
   assert cancelled attempt, task, and run states.
2. Arrange for a successful container exit and a cancellation request to cross
   at a deterministic barrier. Choose and document the precedence rule.

The recommended race rule is: if cancellation was observed and caused the
worker to stop the container, record cancellation; if the container completed
successfully before cancellation was observed, accept success and let run-level
cancellation prevent any remaining queued work. The test should encode that
rule at the exact observation boundary rather than infer it from exit code.

### Verification required

- A real worker path produces cancelled attempt, task, and run states.
- An ordinary exit 137 without a stop signal remains failed.
- Timeout remains distinct from user cancellation.
- The success/cancellation race has one documented deterministic outcome.

## E2-04: Status documents and the consistency checker still disagree

Severity: **Medium governance and release risk**

Resolution (2026-10-01): **Partly addressed**. The contradictions this finding
names are corrected: E1-03 and E1-04 are no longer described as cleanly fixed
by the first response, the G63 row says implemented-and-pending rather than
accepted, the gaps resting on ADRs 0033 and 0034 say which closure criterion
they meet, E1-09 is in the ledger's open list, and the README no longer makes
an unconditional lease-fix claim. `check_consistency.py` now refuses active
prose that calls a pending ADR accepted, which found two more on its first run
-- including ADR 0014, which is still `Proposed`. What is **not** done is the
structural half: there is no machine-readable status file, and the finding
tables in `eval_1.md`, `eval_2.md` and the ledger are still maintained by hand.

Related earlier findings: E1-05 and E1-09

### Problem

The ADR reclassification is a meaningful improvement, but the repository still
contains contradictory active claims:

- `eval_1.md` says E1-04 is fixed.
- The root README says the lease-ownership defect is fixed.
- `14-gap-closure-ledger.md` says all four execution/authorization findings are
  closed.
- The same ledger says ADR 0013 was accepted and G63 is closed, while ADR 0013
  is `Implemented proposal - pending ratification`.
- The ledger similarly treats work based on pending ADRs 0033 and 0034 as
  closed without explaining whether implementation or owner acceptance is the
  closure criterion.
- E1-09 is partly open in `eval_1.md` but is omitted from the ledger's "Still
  open from evaluation 1" list.

The ADR index says a gap is not closed until its ADR is `Accepted` or
`Superseded`. Under that rule, an implemented-but-unratified ADR cannot close
its associated decision gap.

The enhanced consistency checker compares ADR file headers with the ADR index
and verifies the counts in the index summary. It does not inspect claims in the
README, roadmap, ledger, or other active documents. Its source comment says
"every document must agree," but the implementation checks only the ADR index.
The current ADR 0013 contradiction passes the checker and is a concrete example
of E1-09 remaining open.

### Recommended solution

Correct the current record first:

- Mark E1-04 `Partly fixed` in `eval_1.md` and the gap-closure ledger.
- Mark E1-03 `Implemented; end-to-end verification pending`.
- Remove the root README's unconditional lease-fix claim until E2-01 and E2-02
  pass.
- Describe G63, G14, G33, and G93 consistently as implemented but pending
  ratification where their closure depends on ADRs 0013, 0033, or 0034.
- Add E1-09 to the ledger's open/partial list.

Then replace prose as the source of volatile status. A small machine-readable
status file should record, for each evaluation finding and decision gap:

- identifier;
- implementation status;
- verification status;
- decision/ratification status;
- blocking ADRs;
- evidence links;
- owner where human action is required.

Generate summary tables in the README, evaluation status section, and ledger
from that data, or make those documents link to one generated canonical table.
Extend `check_consistency.py` to reject active prose that uses a known ADR ID
with an incompatible status phrase. At minimum, explicit claims such as
"ADR 0013 was accepted" must be checked against ADR 0013's header.

### Verification required

- Changing ADR 0013 to pending while an active document calls it accepted
  fails the consistency check.
- Every Evaluation 1 finding appears exactly once in the canonical status
  data.
- A finding cannot be `fixed` while its required acceptance tests are marked
  incomplete unless the record explicitly documents an accepted exception.
- Generated summaries contain no manually maintained counts.

## Findings that are convincingly addressed

### E1-01: admission control

The transaction-level advisory lock serializes the aggregate admission
decision. A worker that cannot acquire it backs off, and the global resource
sum is evaluated only by the transaction holding the lock. This is a sound
solution for the current one-host/global-budget model.

The limitation is correctly documented: adding a second execution host needs a
host identity on claimed work, a budget row or lock per host, and a per-host
resource sum. Changing only the lock key would be incorrect.

The concurrent test has the right shape: separate sessions, two full-budget
tasks, two workers, and a synchronization barrier. It should remain a mandatory
PostgreSQL test in CI.

### E1-02: publication boundary

Direct `POST /runs` submission now requires an admin principal and records
`requested_from = 'admin'`. Researcher submission remains on the catalog path,
where publication bindings, visibility, fixed values, and type rules are
applied. A search of `submit_run` call sites found no second researcher-facing
raw-revision route.

The missing hidden/fixed-field regression test should still be added, but the
authorization defect itself is closed. ADR 0022 remains a product decision
about whether the admin route should continue to exist, not a reason to reopen
researcher access.

### E1-05: decision honesty

Reclassifying ADRs 0008, 0013, 0015, and 0031-0034 as implemented proposals
pending ratification is correct. Each ADR now states what has already been
built and therefore exposes the cost of choosing differently. That is useful
decision material rather than an attempt to force acceptance.

The remaining work is genuinely the owner's: ratify, amend, reject, or defer
the proposals. The repository should not silently restore `Accepted` status
until an approver and date are recorded.

## Recommended order of work

### 1. Correct the record

Update `eval_1.md`, the root README, and the gap-closure ledger so E1-03 and
E1-04 are not represented as fully closed. Correct the ADR 0013/G63
contradiction and list E1-09 as partial.

Exit condition: active status documents agree with this evaluation and with
the ADR headers.

### 2. Make finalization atomic with ownership

Implement the E2-01 ownership lock and E2-02 guarded attempt transition. Keep
artifact registration, delivery planning, attempt completion, and task
completion in one coherent transaction after ownership is verified.

Exit condition: the deterministic old-worker/new-worker race leaves no losing
artifacts or deliveries and cannot rewrite a lost attempt.

### 3. Complete cancellation acceptance testing

Test cancellation through the API, heartbeat, watcher, adapter, executor, and
run aggregator. Decide and encode the natural-success race rule.

Exit condition: attempt, task, and run cancellation are demonstrated through
the real orchestration path.

### 4. Run the database-backed suite

Start PostgreSQL, apply migrations, and run the complete backend suite,
Alembic drift check, the admission race, and the new finalization races. The
previous response reports green database tests, but this evaluation could not
independently reproduce them with Docker unavailable.

Exit condition: no database tests are skipped and all migration checks pass on
a clean database.

### 5. Finish the decision review and canonical workflow work

Continue with the still-open Evaluation 1 items only after the correctness
record is accurate: owner ratification, ADR 0016 and the representative
workflow matrix, CI, project-scoped mounts, fixture review, and production OS
selection.

Exit condition: correctness fixes no longer compete with feature expansion,
and production-readiness claims are backed by both owner decisions and
repeatable evidence.

## Conclusion

The response to Evaluation 1 should be retained, not reverted. It fixed the
most direct task-row corruption and restored much-needed honesty to the ADR
queue. The remaining work is narrower than the original findings, but it is
not cosmetic: finalization must treat task ownership, attempt state, artifacts,
deliveries, dependants, and run advancement as one consistency boundary.

Until that boundary and the cancellation acceptance path are tested, the
project remains a strong prototype undergoing acceptance rather than a
production-ready pipeline platform.
