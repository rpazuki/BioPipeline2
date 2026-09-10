# ADR 0005: Task entry-point contract

Date: 2026-09-10
Status: Accepted
Decision owner: Roozbeh Pazuki
Decision deadline: Before Phase 1 closes
Related question: [Q5](../../13-open-questions.md)
Related gaps: G20

## Context

Define how a workflow invokes external science code under container execution.

This ADR exists because the migration plan cannot safely proceed on this topic by implication. The linked gap row records the evidence from the current `bioPipeline` source tree; this document records the actual project decision.

## Options

- Option A: A JSON task specification written to a known path, read by the image's entry point. Mirrors the current `TASK.json` subprocess convention.
- Option B: Arguments passed on the command line.
- Option C: A Python API the science library must implement against.

## Decision

**Option A**, specified in
[`docs/architecture/task-entry-point-contract.md`](../../../docs/architecture/task-entry-point-contract.md)
and implemented as [`app/domain/task_contract.py`](../../../backend/app/domain/task_contract.py),
contract version 1.0.

The worker writes a `TaskSpec` to `/work/.bp/task.json`; the container reads it,
works, and writes a `TaskResult` to `/work/.bp/result.json`. Exit code 0 plus a
valid result means success. The worker verifies declared outputs itself and
never trusts the task's own report.

`CallableRef(kind="python_callable", module=..., attribute=...)` maps directly
onto the existing `package` / `method` convention, so science functions are
adapted rather than rewritten. `kind="command"` covers non-Python tools.

## Consequences

- Task images depend on this contract, so it is versioned and unknown fields are rejected in both directions.
- Declaring outputs up front is what makes a run auditable and lets a task that exits 0 without producing them fail.
- `TaskError.kind` distinguishes bad input from a crash, so the UI can say "your sample sheet is malformed" rather than "exit code 1".
- Assumes tasks need no secrets; the model rejects credential-shaped environment variables. If ADR 0023 decides otherwise, this contract changes.

## Follow-up updates required

- Update `../../gaps.md` if this closes or supersedes a `Decision needed` row.
- Update `../../14-gap-closure-ledger.md` with the accepted decision and any implementation work created from it.
- Update the affected design document referenced by the gap row.
- Add implementation tickets, tests, or release notes if the decision changes v1 scope.
