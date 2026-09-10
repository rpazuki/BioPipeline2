# ADR 0009: Tenancy and project scope

Date: 2026-09-10
Status: Accepted
Decision owner: Roozbeh Pazuki
Decision deadline: Before Phase 1 schema work
Related question: [Q9](../../13-open-questions.md)
Related gaps: G29

## Context

Decide whether BioPipeline2 is single-project, project-scoped, or multi-tenant.

This ADR exists because the migration plan cannot safely proceed on this topic by implication. The linked gap row records the evidence from the current `bioPipeline` source tree; this document records the actual project decision.

## Options

- Option A: No tenancy. Drop persistence rule 8.
- Option B: Carry `project_id` columns and a `projects` table from the first migration, seeded with one default project, but build no scoping UI or API.
- Option C: Full multi-project scoping with per-project RBAC.

## Decision

**Option B.** One lab of 5-20 people is a single-project deployment.

`projects` and `project_members` exist and every owned entity carries
`project_id`, with one default project seeded by the base migration and a
partial unique index guaranteeing exactly one default. No API route, index or
UI scopes by project.

## Consequences

- Adding the columns later would be a migration across every large table; leaving them unused costs a few bytes per row.
- The columns are inert, which is a mild trap: a future contributor may assume scoping works. Documented in [`ASSUMPTIONS.md`](../../../ASSUMPTIONS.md).
- Fair-share scheduling and per-user quotas are out of scope; resource admission control replaces them.

## Follow-up updates required

- Update `../../gaps.md` if this closes or supersedes a `Decision needed` row.
- Update `../../14-gap-closure-ledger.md` with the accepted decision and any implementation work created from it.
- Update the affected design document referenced by the gap row.
- Add implementation tickets, tests, or release notes if the decision changes v1 scope.
