# ADR 0029: Resource admission control instead of a serial queue

Date: 2026-09-10
Status: Accepted
Decision owner: Roozbeh Pazuki
Decision deadline: Before Phase 1 closes
Related gaps: G18, G64

## Context

Task duration spans four orders of magnitude: measured 0.8-47.8 seconds today,
with RNA-seq alignment planned at hours to a day per sample. Heavy tasks must not
run concurrently or they exhaust the VM, but short tasks should still pack
together. The operator should not have to maintain two queues, and the author
should not have to pick one.

## Options

- Option A: A global concurrency limit of one for everything.
- Option B: Separate serial and parallel queues, chosen per pipeline.
- Option C: Resource requests plus admission control.

## Decision

**Option C.** Each task declares CPU millicores, memory bytes, a wall-time limit
and optionally `exclusive`. A worker claims a task only if its request fits the
budget not already committed to running tasks.

Sequential execution of heavy work falls out of the arithmetic: a task requesting
the whole budget cannot be admitted while anything else holds resources, and
nothing else can be admitted while it runs. No separate mode.

Implemented in [`app/infrastructure/db/claiming.py`](../../../backend/app/infrastructure/db/claiming.py);
documented in [`docs/architecture/execution-model.md`](../../../docs/architecture/execution-model.md).

## Consequences

- The budget check runs inside the claiming transaction, so concurrent workers cannot jointly over-commit; `FOR UPDATE SKIP LOCKED` keeps them off the same row. Both are tested against real PostgreSQL.
- Admission control alone allows starvation, so the claim query refuses to admit a task younger than the oldest task that does not fit. A waiting alignment job drains the queue ahead of itself.
- Budgets must be set below the host's real capacity: the API, database and OS need headroom the scheduler does not model.
- Task classes (`small`, `standard`, `large`, `exclusive`) are conventional labels; the request columns are what the scheduler reads.

## Follow-up updates required

- Update `../../gaps.md` if this closes or supersedes a row.
- Update `../../14-gap-closure-ledger.md`.
- Update the affected design document.
