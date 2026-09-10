# ADR 0019: Password hash portability and reset policy

Date: 2026-09-10
Status: Accepted (moot)
Decision owner: Roozbeh Pazuki
Decision deadline: Before user importer build
Related question: [Q19](../../13-open-questions.md)
Related gaps: G86

## Context

Decide whether existing password hashes transfer or all users must reset credentials.

This ADR exists because the migration plan cannot safely proceed on this topic by implication. The linked gap row records the evidence from the current `bioPipeline` source tree; this document records the actual project decision.

## Options

- Option A: TBD.
- Option B: TBD.
- Option C: TBD, if applicable.

## Decision

**Moot.** No users are imported. The five existing accounts are re-created,
and the first admin is created by the bootstrap path (ADR 0004, still open).

Password hashing for the new system is Argon2id, chosen independently of any
portability constraint.

## Consequences

- Removes work from the roadmap; see [09-migration-roadmap.md](../../09-migration-roadmap.md).

## Follow-up updates required

- Update `../../gaps.md` if this closes or supersedes a `Decision needed` row.
- Update `../../14-gap-closure-ledger.md` with the accepted decision and any implementation work created from it.
- Update the affected design document referenced by the gap row.
- Add implementation tickets, tests, or release notes if the decision changes v1 scope.
