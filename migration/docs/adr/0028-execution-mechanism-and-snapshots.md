# ADR 0028: Execution mechanism and environment snapshots

Date: 2026-09-10
Status: Accepted (amended 2026-09-10)
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

**Option C, amended.** The container-plus-mounted-virtualenv shape stands. The
*snapshot mechanism* is replaced by **immutable generations**, because
per-run cloning was not a dependable isolation design:

- hardlinks are not an isolation boundary when an installer rewrites a file in
  place;
- copy-on-write cloning depends on filesystem support the target VM has not
  guaranteed;
- virtualenvs embed absolute interpreter paths and are not generally
  relocatable;
- native wheels must match the interpreter, libc, architecture and image;
- a package-name/version list is not a content identity for editable installs,
  dirty VCS trees or local wheels;
- per-run cloning gets expensive once environments reach gigabytes.

Immutable generations instead:

1. An admin requests an install, uninstall or upgrade.
2. The package manager builds a **new generation out of place**, inside the same
   container image, so interpreter and ABI match by construction.
3. It installs, validates, inventories and content-hashes that generation.
4. On success it atomically moves the environment's `current_generation_id`.
5. A run pins a generation. Existing runs never observe later installs.
6. Unreferenced generations are garbage-collected after a retention period.

No cloning, no relocation, and isolation comes from never mutating a generation
rather than from filesystem tricks.

`package_operations` records install history as provenance: it answers why a
pipeline that worked last month fails today.

## Consequences

- Installs never disturb running work, and a run records exactly what it used, giving provenance without an image registry.
- A generation is written once and never mutated, so isolation does not depend on filesystem features.
- Generations are shared by every run that pins them; storage grows per install, not per run.
- Containers give resource limits, timeouts and crash isolation. They are **not** a security boundary: code is admin-authored and trusted (ADR pending on trust model). Researcher-supplied *input* remains untrusted, so path containment and validation stay strict.
- **Editable installs.** The real install history includes `labUtils` installed editable from a working tree, which no generation can capture: it is a link to mutable source. For development that is acceptable if the run is marked non-reproducible. For published, reproducible execution the library must be built into a wheel or source snapshot first — marking the run non-reproducible is not an adequate default production provenance story.
- **Feasibility is unproven.** Before this is relied upon: prove isolation during a concurrent upgrade, prove the environment works inside the exact production task image, test native extensions and editable installs explicitly, and measure disk growth and generation garbage collection. ADR must record the filesystem, interpreter and ABI assumptions once measured.

## Follow-up updates required

- Update `../../gaps.md` if this closes or supersedes a row.
- Update `../../14-gap-closure-ledger.md`.
- Update the affected design document.
