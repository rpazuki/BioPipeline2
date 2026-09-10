# ADR 0028: Execution mechanism and environment snapshots

Date: 2026-09-10
Status: Accepted
Decision owner: Roozbeh Pazuki
Decision deadline: Before Phase 1 closes
Related gaps: G06, G51

## Context

Document 06 proposed immutable pinned container images per runtime environment.
That conflicts with how the system is actually used: admins install libraries
into a shared virtualenv as part of normal work, so a frozen image turns every
`pip install` into an image build.

But a mutable shared environment conflicts with long-running work. Tasks will run
for up to a day (ADR 0006), and an install landing mid-run would change the
environment underneath it. The current system guards installs while jobs run,
which is untenable for a day-long task.

## Options

- Option A: Pinned images per environment.
- Option B: Subprocess execution in a managed virtualenv, as the current system does.
- Option C: One task container image with the admin-managed virtualenv mounted in, and a per-run snapshot of that virtualenv.
- Option D: Queue installs until the system is idle.

## Decision

**Option C.**

One thin task image supplies the runner; the virtualenv supplies the libraries
and stays mutable and installable. A run binds to an `environment_snapshots` row
at submission — a copy-on-write or hardlinked clone plus the resolved package
list — and every task of that run executes against it.

`package_operations` records install history as provenance: it answers why a
pipeline that worked last month fails today.

## Consequences

- Installs never disturb running work, and a run records exactly what it used, giving provenance without an image registry.
- Identical package sets share one snapshot by content digest rather than cloning per run.
- Containers give resource limits, timeouts and crash isolation. They are **not** a security boundary: code is admin-authored and trusted (ADR pending on trust model). Researcher-supplied *input* remains untrusted, so path containment and validation stay strict.
- **Known limitation.** The real install history includes `labUtils` installed editable from a working tree. An editable install is a link to source, so a snapshot cannot capture it: two runs against the same snapshot may execute different code. The snapshot logic must detect editable distributions and record that the run is not reproducible rather than claiming provenance it cannot deliver.

## Follow-up updates required

- Update `../../gaps.md` if this closes or supersedes a row.
- Update `../../14-gap-closure-ledger.md`.
- Update the affected design document.
