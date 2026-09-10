# ADR 0024: Developer platform parity

Date: 2026-09-10
Status: Accepted
Decision owner: Roozbeh Pazuki
Decision deadline: Before development environment standardization
Related question: [Q24](../../13-open-questions.md)
Related gaps: G75

## Context

Decide which developer platforms are supported and how they emulate Red Hat/Podman/SELinux behavior.

This ADR exists because the migration plan cannot safely proceed on this topic by implication. The linked gap row records the evidence from the current `bioPipeline` source tree; this document records the actual project decision.

## Options

- Option A: Devcontainer or remote development VM.
- Option B: Docker on each developer's own OS, matching production.
- Option C: Native development with a separate execution path per platform.

## Decision

**Option B.** Production is Docker on Linux (ADR 0008); developers run
the same Docker runtime on Windows, macOS or Linux.

`make setup` creates the virtualenv, `make db-up` starts PostgreSQL via compose,
`make check` runs what CI runs. No platform-specific execution path.

## Consequences

- The Podman and SELinux divergence that made this question urgent no longer exists.
- The current project's Windows-only development commands are not carried over; paths in the new codebase are POSIX and the container boundary is identical everywhere.
- Existing pipeline YAML uses Windows paths (`H:\ROBOT_SCIENTIST\...`, `C:\Users\...`). Re-authoring must translate them; there is no importer to do it automatically.

## Follow-up updates required

- Update `../../gaps.md` if this closes or supersedes a `Decision needed` row.
- Update `../../14-gap-closure-ledger.md` with the accepted decision and any implementation work created from it.
- Update the affected design document referenced by the gap row.
- Add implementation tickets, tests, or release notes if the decision changes v1 scope.
