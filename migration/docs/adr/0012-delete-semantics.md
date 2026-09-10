# ADR 0012: Delete semantics for runs and artifacts

Date: 2026-09-10
Status: Accepted
Decision owner: Roozbeh Pazuki
Decision deadline: Before Phase 1 data model finalization
Related question: [Q12](../../13-open-questions.md)
Related gaps: G36

## Context

Decide soft delete, hard delete, expiry, backup interaction, and verifiable deletion semantics.

This ADR exists because the migration plan cannot safely proceed on this topic by implication. The linked gap row records the evidence from the current `bioPipeline` source tree; this document records the actual project decision.

## Options

- Option A: Hard delete on request.
- Option B: TTL-based cleanup of bytes, with run history surviving.
- Option C: Nothing is removed automatically.
- Option D: Fully ephemeral, including run history.

## Decision

**Option B.** Input and output bytes are removed on a TTL; the run
record, its submitted parameters, and its logs survive for provenance.

`artifacts.deleted_at` marks a row as withdrawn; `artifacts.purged_at` records
that the bytes are actually gone, which is what makes deletion verifiable rather
than merely recorded. `runs.deleted_at` is a soft delete so the audit trail
survives a user removing a run from their view.

There is deliberately **no `expired` run status**: a run whose outputs were later
cleaned still succeeded, so expiry is a fact about artifacts and workspaces, not
an overwrite of the outcome.

## Consequences

- "What did I run last week, with what parameters, and did it work?" stays answerable after the data is gone.
- The janitor is load-bearing for disk headroom, especially once RNA-seq intermediates exist.
- Failed runs are kept. The real deployment's 100% success rate came from deleting failures by hand; the UI must make failures filterable and archivable so the evidence survives.

## Follow-up updates required

- Update `../../gaps.md` if this closes or supersedes a `Decision needed` row.
- Update `../../14-gap-closure-ledger.md` with the accepted decision and any implementation work created from it.
- Update the affected design document referenced by the gap row.
- Add implementation tickets, tests, or release notes if the decision changes v1 scope.
