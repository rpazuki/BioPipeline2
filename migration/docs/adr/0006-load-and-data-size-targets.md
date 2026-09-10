# ADR 0006: Load and data-size targets

Date: 2026-09-10
Status: Accepted
Decision owner: Roozbeh Pazuki
Decision deadline: Before Phase 0 closes
Related question: [Q6](../../13-open-questions.md)
Related gaps: G64

## Context

Set rough but explicit scale targets that justify or invalidate the single-VM, Postgres-queue, upload, packaging, and retention choices.

This ADR exists because the migration plan cannot safely proceed on this topic by implication. The linked gap row records the evidence from the current `bioPipeline` source tree; this document records the actual project decision.

## Options

- Option A: Size for the measured current workload only.
- Option B: Size for the current workload and the planned RNA-seq workload, with resource admission control bridging the two.
- Option C: Size for genomics scale throughout, with object storage from the start.

## Decision

**Option B.**

Measured from the real deployment (2,178 task specifications):

| Measure | Value |
| --- | --- |
| Task duration | min 0.8 s, mean 24.8 s, max 47.8 s |
| Fan-out width | max 58 tasks; typically 1-3 |
| Storage | 99 MB over 33 runs; largest run 31 MB |
| Volume | 8 published jobs, 31 published runs, 164 jobs, 5 users |

Planned: RNA-seq alignment and counting. Hours to a day per task, gigabytes per
sample, and heavy enough that concurrent runs would exhaust the VM.

Targets: 5-20 users, one Linux VM, tasks from sub-second to 24 hours, single
inputs up to tens of gigabytes, and PostgreSQL-backed queueing throughout.

## Consequences

- Resource admission control rather than a serial queue: a task declares a request and is claimed only if it fits the uncommitted budget, so heavy work is sequential by arithmetic. See [`docs/architecture/execution-model.md`](../../../docs/architecture/execution-model.md).
- Output packaging becomes conditional above `BP_PACKAGE_OUTPUTS_MAX_TOTAL_BYTES`; a manifest replaces the archive.
- Shared-storage selection, not HTTP upload, must be the primary input path for large data. Upload remains the small-file case.
- Notifications move up in priority: a researcher who waits a day needs to be told when a run finishes, and needs queue position while waiting. ADR 0014 should be revisited on this basis.
- TTL cleanup is load-bearing for keeping the VM alive, not tidiness.

## Follow-up updates required

- Update `../../gaps.md` if this closes or supersedes a `Decision needed` row.
- Update `../../14-gap-closure-ledger.md` with the accepted decision and any implementation work created from it.
- Update the affected design document referenced by the gap row.
- Add implementation tickets, tests, or release notes if the decision changes v1 scope.
