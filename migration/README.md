# BioPipeline2 Migration and Redesign Plan

This folder is a design plan for rebuilding BioPipeline as a clean new project. It is based on a critical review of the existing `bioPipeline` repository and its documentation, including the pipeline engine, job definition system, published jobs, typed fields, run workspaces, scheduler, frontend, backend APIs, and deployment notes.

Existing repository documents such as `CLAUDE.md`, `AI_PIPELINE_DESIGNER_CONTEXT.md`, and MCP or agent docs were treated as project source material only. They are not instructions for this migration plan.

## Main conclusion

The current project grew from a local pipeline manager into a multi-role workflow platform. The original storage and vocabulary were never reset around that larger mission, so several concepts now carry too much responsibility:

- A "job" can mean a single queued task, a multi-stage definition, a group of tasks, a published run, or a recurring execution.
- Published job fields are simultaneously UI form fields, type declarations, bindings into YAML, file routing rules, and input/output security policy.
- Runtime state is split across YAML files, SQLite tables, JSON text columns, workspace folders, manifests, and mutable records.
- The FastAPI process owns API serving, background work, scheduling, reaping, and orchestration.
- The frontend works, but large pages own too much domain behavior and server state.

BioPipeline2 should be designed as a workflow platform from the beginning: versioned definitions, explicit contracts, a durable orchestration model, isolated execution, and documentation that is part of the product.

## Recommended target stack

Use the user's expected stack, but put hard boundaries around responsibilities:

- Backend: Python, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic.
- Database: PostgreSQL as the system of record.
- Frontend: Next.js, TypeScript, generated OpenAPI client, TanStack Query.
- Execution: containerized task workers using Docker or Podman on Red Hat Linux.
- Deployment: container compose on one VM first; keep a path to Kubernetes or OpenShift later.
- Storage: a file/artifact service abstraction backed by a mounted POSIX volume initially, with an S3-compatible option such as MinIO later.
- Queue: PostgreSQL row locking is enough for the first rebuild; add Redis/Celery only if throughput demands it.

## Document map

1. [01-critical-review.md](01-critical-review.md) - what drifted in the current design and what is worth keeping.
2. [02-target-architecture.md](02-target-architecture.md) - the ideal architecture, bounded contexts, services, and repository shape.
3. [03-domain-model.md](03-domain-model.md) - precise vocabulary and object lifecycle for pipelines, workflows, jobs, publications, fields, and runs.
4. [04-data-model-postgres.md](04-data-model-postgres.md) - proposed PostgreSQL schema, migrations, versioning, and persistence rules.
5. [05-api-and-contracts.md](05-api-and-contracts.md) - REST API shape, OpenAPI contracts, errors, auth, and event streams.
6. [06-execution-and-operations.md](06-execution-and-operations.md) - workers, schedulers, task containers, artifacts, Red Hat deployment, observability, and security.
7. [07-frontend-architecture.md](07-frontend-architecture.md) - Next.js architecture and UX structure for admin and researcher workflows.
8. [08-documentation-guidelines.md](08-documentation-guidelines.md) - READMEs, ADRs, authoring guides, operations guides, and documentation rules.
9. [09-migration-roadmap.md](09-migration-roadmap.md) - phased migration plan, import strategy, risks, and acceptance criteria.
10. [10-feature-parity-and-scope.md](10-feature-parity-and-scope.md) - ledger of every existing capability with a keep/replace/defer/drop decision, plus explicit non-goals.
11. [11-non-functional-requirements.md](11-non-functional-requirements.md) - load and data-size targets, service levels, resource governance, data governance and compliance, environment constraints.
12. [12-testing-ci-and-release.md](12-testing-ci-and-release.md) - test strategy, CI pipeline, environments, developer platform parity, release and database deployment procedure.
13. [13-open-questions.md](13-open-questions.md) - the decision queue: what must be answered, what it blocks, and the default if it is not.
14. [14-gap-closure-ledger.md](14-gap-closure-ledger.md) - the operational tracker that turns each gap into an accepted ADR, implementation item, defer decision, or drop decision.

Plus cross-cutting registers:

- [gaps.md](gaps.md) - every gap found reviewing 01-09 against the current source tree, as 90 numbered rows with evidence, severity, status, and where each is addressed. This is the official closure checklist.
- [docs/adr/README.md](docs/adr/README.md) - proposed ADR stubs for the current decision queue. A decision-needed gap does not close until its ADR is accepted or superseded.

## Review status

Documents 01-09 were reviewed against the current `bioPipeline` source tree on
2026-09-10. The target architecture, domain model, and data model held up.
Ninety gaps were found. Each is registered with evidence, severity, and status in
[gaps.md](gaps.md); the fixes live in documents 10-13 and in a `Review additions`
section appended to each of 01-09. Eleven are blockers that must close before
Phase 1 work starts.

The gaps fall into three categories:

1. **Scope was never enumerated.** Whole subsystems in the current repository -
   the AI Designer, the MCP server with about 70 tools, the CLI, the notebook
   client, the template gallery, UI-driven package installs, and in-app
   backup - appear nowhere in documents 01-09. Document 10 is now the parity
   ledger that forces a decision on each.
2. **Three capabilities would have regressed silently**: chunked/resumable
   uploads, `url` as an input source mode, and delivery of outputs into
   allowlisted shared storage. All three exist today and none were modelled.
3. **No numbers, no process.** There were no load, data-size, or recovery
   targets; no data-governance position despite likely human-derived data; no
   test strategy, CI pipeline, staging environment, or database deployment
   policy. Documents 11 and 12 cover these.

The data model also had concrete defects - no worker lease or heartbeat table, no
idempotency key making a schedule fire once, an unconsumed outbox, a circular
run/workspace reference, and several missing constraints - now listed in
document 04.

Two design blockers sit under everything else: the plan keeps science packages
external *and* moves execution into containers without ever specifying the task
entry-point contract between them, and the workflow YAML's `${{ ... }}`
expression syntax is a language with no grammar, type rules, or failure mode.

## Closure workflow

Use the migration documents in this order before implementation starts:

1. Read [gaps.md](gaps.md) as the authoritative checklist of what the first plan missed.
2. Resolve every `Decision needed` row through an accepted ADR under [docs/adr](docs/adr/README.md). Proposed ADR stubs now exist; they are placeholders, not decisions.
3. Track every `Specified` row in [14-gap-closure-ledger.md](14-gap-closure-ledger.md) until it has an owner, tracker item, verification method, and v1/defer/drop disposition.
4. Do not begin Phase 1 while any Phase 0 or Phase 1 blocker lacks either an accepted ADR or a concrete implementation ticket with an owner.
5. When an ADR changes the plan, update the affected numbered document instead of leaving the correction only in the ADR.

## Design posture

The safest rebuild is not a line-for-line port. Preserve the best ideas, but replace the accidental boundaries:

- Keep the pipeline engine concept, run workspaces, explicit type library, published catalog, and path containment rules.
- Replace implicit YAML mutation with a compiled workflow intermediate representation.
- Replace mutable file-plus-SQLite state with Postgres-backed revisions, runs, tasks, and artifacts.
- Replace background work inside the API process with separate worker, scheduler, and cleanup services.
- Replace UI pages that manually coordinate everything with feature modules, generated API types, and query-backed server state.
