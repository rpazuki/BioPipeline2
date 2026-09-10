# ADR 0011: Enum representation

Date: 2026-09-10
Status: Accepted
Decision owner: Roozbeh Pazuki
Decision deadline: Before Phase 1 migrations
Related question: [Q11](../../13-open-questions.md)
Related gaps: G37

## Context

Choose a single database and application enum policy.

This ADR exists because the migration plan cannot safely proceed on this topic by implication. The linked gap row records the evidence from the current `bioPipeline` source tree; this document records the actual project decision.

## Options

- Option A: Native PostgreSQL enum types.
- Option B: `text` plus a named CHECK constraint.
- Option C: Lookup tables with foreign keys.

## Decision

**Option B.** Every constrained string is `text` with a named CHECK
constraint generated from `app.domain.enums`.

`DomainEnum.check_values()` renders the constraint body, so the database and the
API cannot disagree about the allowed set: adding a value means editing one
Python enum and generating a migration.

## Consequences

- Adding a value is an ordinary migration. PostgreSQL cannot drop an enum label, which Option A would have made permanent.
- Constraint names are short suffixes, because the naming convention prepends `ck_<table>_`. Passing a full name once produced 38 double-prefixed, hash-truncated constraint names; a test now guards against it.
- 76 check constraints exist and are individually tested for actually rejecting bad rows.

## Follow-up updates required

- Update `../../gaps.md` if this closes or supersedes a `Decision needed` row.
- Update `../../14-gap-closure-ledger.md` with the accepted decision and any implementation work created from it.
- Update the affected design document referenced by the gap row.
- Add implementation tickets, tests, or release notes if the decision changes v1 scope.
