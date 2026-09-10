# ADR 0008: Production container runtime and network constraints

Date: 2026-09-10
Status: Accepted
Decision owner: Roozbeh Pazuki
Decision deadline: Before Phase 0 closes
Related question: [Q8](../../13-open-questions.md)
Related gaps: G68

## Context

Decide Docker versus rootless Podman, outbound internet availability, internal registry requirements, and VM constraints.

This ADR exists because the migration plan cannot safely proceed on this topic by implication. The linked gap row records the evidence from the current `bioPipeline` source tree; this document records the actual project decision.

## Options

- Option A: Rootless Podman on Red Hat with SELinux volume labels, as document 06 assumed.
- Option B: Docker on a generic Linux VM.
- Option C: Keep the execution adapter abstract and decide later.

## Decision

**Option B.** Docker on a Linux VM. No Red Hat, Podman or SELinux
specifics.

The execution adapter stays behind an interface so Podman remains reachable, but
the documentation, compose files and defaults target Docker.
`BP_CONTAINER_RUNTIME` defaults to `docker`.

## Consequences

- Document 06's SELinux volume labelling and rootless-Podman guidance is removed.
- Deployment documentation simplifies considerably.
- Development on Windows and macOS uses the same Docker runtime, so ADR 0024 largely dissolves.
- If the institution later mandates Podman, the adapter interface is the seam.

## Follow-up updates required

- Update `../../gaps.md` if this closes or supersedes a `Decision needed` row.
- Update `../../14-gap-closure-ledger.md` with the accepted decision and any implementation work created from it.
- Update the affected design document referenced by the gap row.
- Add implementation tickets, tests, or release notes if the decision changes v1 scope.
