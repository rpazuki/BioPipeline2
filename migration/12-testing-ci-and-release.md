# Testing, CI, and Release Engineering

Documents 01-09 mention tests in scattered acceptance criteria and list a few CI
doc checks in 08, but there is no test strategy, no CI pipeline, no environment
model, and no release or database-deployment procedure. Document 01 credits the
current project with "meaningful test coverage" - that is an asset the rebuild
should not lose by accident.

Registered as rows G70-G77 of [gaps.md](gaps.md).

## Test strategy

### Backend

| Layer | What it covers | Tooling | Speed target |
| --- | --- | --- | --- |
| Domain unit tests | Invariants, state machines, compiler rules. No I/O. | pytest | milliseconds; the bulk of the suite |
| Application service tests | Use cases against a real Postgres in a container | pytest + testcontainers (or a session-scoped Docker/Podman Postgres) | seconds |
| Repository / migration tests | Fresh DB migrates to head; downgrade where practical; constraints actually reject bad rows | pytest + Alembic | seconds |
| API contract tests | Route -> service wiring, auth and authorization per route, error shape | pytest + httpx ASGI client | seconds |
| Execution adapter tests | Container launch, log streaming, output collection, timeout, cancellation, non-zero exit | pytest, real Podman/Docker, marked `slow` | minutes |
| End-to-end | Submit through to artifact download against a composed stack | pytest or Playwright against compose | minutes |

Rules worth fixing early, because they are cheap now and expensive later:

- **Never test against SQLite.** The plan commits to Postgres-specific features
  (`FOR UPDATE SKIP LOCKED`, JSONB, `citext`, `inet`, partial indexes). A SQLite
  test path would silently diverge.
- **Authorization is a test matrix, not a spot check.** For every route: anonymous,
  researcher-owner, researcher-non-owner, admin. Document 05 says backend
  authorization is authoritative; prove it per route.
- **Every compiler rejection in Phase 2 needs a named test**: cycles, missing
  inputs, unknown pipeline reference, type mismatch, path escape, fan-out from a
  non-existent output, duplicate stage name, expression parse failure.
- **Determinism test for compilation**: same source twice yields the same
  `graph_hash`.
- **Concurrency tests**: two workers cannot claim the same task; two scheduler
  instances cannot double-fire one schedule window; two submits with the same
  idempotency key create one run.
- **Crash-recovery tests**: kill a worker mid-task and assert the lease expires
  and the task is retried or failed, not stranded in `claimed`.

### Frontend

Document 07's list is a good start. Add:

- Generated-client drift test: regenerating from the committed OpenAPI produces
  no diff. A stale client is the most likely frontend break in this design.
- Schema-driven form rendering tests per field kind, including the typed-object
  editor and the shared-storage browser.
- Large-upload behavior: chunk retry, resume, cancel, progress.
- Accessibility checks on the core screens (keyboard navigation, labels, focus
  management, contrast). Not mentioned anywhere in 07 and hard to retrofit.

### Contract tests for non-frontend consumers

If the CLI, notebook client, or MCP server survive
([10-feature-parity-and-scope.md](10-feature-parity-and-scope.md) rows 17-19),
each must have a smoke suite in CI that fails when a route changes shape.
Otherwise they will rot exactly as the legacy docs did.

## CI pipeline

Minimum pipeline on every pull request:

1. Lint and format: ruff and mypy (backend), eslint and `tsc --noEmit` (frontend).
2. Backend unit and application tests with a Postgres service container.
3. Alembic: fresh database to head, plus a check that models and migrations agree
   (autogenerate produces an empty diff).
4. OpenAPI: regenerate `contracts/openapi.json`; fail if it differs from the
   committed file. Fail on a breaking change unless the PR is labelled for it.
5. Frontend: regenerate the client from the committed OpenAPI; fail on diff. Then
   unit tests and build.
6. Example validation: every file in `examples/` compiles cleanly (this is the
   Phase 2 regression net).
7. Doc checks from document 08: link check, deprecated-name check.
8. Build the container images.

Nightly or on-merge, not per PR:

- Execution adapter tests against real Podman.
- End-to-end compose suite.
- Restore rehearsal: restore the previous nightly backup into a scratch stack and
  run one workflow.
- Image vulnerability scan for API, worker, and task base images.

## Environments

| Environment | Purpose | Data |
| --- | --- | --- |
| Local dev | Compose stack per developer | Seeded synthetic |
| CI | Ephemeral per pipeline run | Seeded synthetic |
| Staging | Release rehearsal, upgrade and migration rehearsal, operator training | Synthetic or de-identified only |
| Production | Red Hat VM | Real |

A staging environment is a hard requirement for the Phase 9 cutover: rehearsing
the legacy import and the upgrade path against production-shaped data is the only
way the parallel-run phase means anything. Documents 06 and 09 assume one VM.

### Developer platform parity

The current project is developed on Windows (`.venv/Scripts/python.exe`,
PowerShell commands throughout the legacy `CLAUDE.md`), while the target runtime
is rootless Podman on Red Hat with SELinux volume labels. That gap is not
addressed in any document. Decide, and write it in `backend/README.md`:

- Which container runtime developers use on Windows and macOS.
- Whether SELinux-specific mount flags are applied conditionally.
- Whether a devcontainer or a remote dev VM is the supported path.

Left unresolved, "works on my machine" failures will be attributed to the
architecture rather than to the dev environment.

## Release engineering

- **Versioning**: semantic version on the repository; the API keeps `/api/v1`
  independently. Record both in `/health` output and in the UI footer so an
  operator can state exactly what is deployed.
- **Changelog**: generated per release, with an explicit "operator actions
  required" section (new environment variables, migrations, image rebuilds).
- **Branching**: trunk-based with short-lived branches and release tags is enough
  for this team size; state it rather than leaving it implicit.
- **Migration deployment policy**: expand/contract. Every release must be
  deployable as (1) migrate forward, (2) deploy new code, and never require the
  reverse order. Destructive column drops happen a release later than the code
  that stopped using them. Without this rule, "rollback release" in document 06
  is not actually possible once a migration has run.
- **Migration safety rules**: no long-held `ACCESS EXCLUSIVE` locks on `runs`,
  `run_tasks`, or `artifacts`; create indexes concurrently; add `NOT NULL` via a
  validated check constraint; backfill in batches. These tables will be the
  largest and the most contended.
- **Upgrade procedure**: drain workers (stop claiming, let running tasks finish or
  cancel with notice), stop scheduler, migrate, deploy, restart. Document the
  expected downtime and whether long-running tasks survive an upgrade.
- **Rollback procedure**: previous image tags pinned and retained; a stated policy
  for what happens to runs created by the newer version.
- **Seed and demo data**: one command that produces a working admin, a sample
  pipeline, workflow, publication, type, and a completed run. Every phase's
  acceptance criteria depend on this existing; make it a Phase 1 deliverable.
