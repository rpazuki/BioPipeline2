# Documentation Guidelines

## Documentation goals

BioPipeline2 documentation should make the system easier to operate, extend, and audit. It should not mix historical notes, active architecture, and agent instructions without labels.

Every document should answer:

- Who is this for?
- Is this current or historical?
- Which code or contract owns the truth?
- How do I verify the behavior?

## Required README files

### Root `README.md`

Audience: developers and evaluators.

Must include:

- What BioPipeline2 is.
- Quick start for local development.
- Architecture summary.
- Repository map.
- Links to authoring, publishing, deployment, and operations docs.
- Supported deployment target.
- Test commands.

### `backend/README.md`

Audience: backend developers.

Must include:

- Backend architecture layers.
- How to run API, worker, scheduler, and janitor locally.
- Database migrations.
- Test strategy.
- Coding conventions.
- How to add an API route.
- How to add an application service.

### `frontend/README.md`

Audience: frontend developers.

Must include:

- App routing structure.
- Feature folder conventions.
- Generated API client workflow.
- Design system usage.
- Test commands.
- Path prefix and environment configuration.

### `deploy/README.md`

Audience: operators.

Must include:

- Linux VM prerequisites.
- Docker setup.
- Compose/systemd commands.
- Environment variables.
- TLS and reverse proxy setup.
- Backup and restore.
- Upgrade and rollback.
- Troubleshooting.

## Required docs

```text
docs/
  architecture/
    overview.md
    domain-model.md
    data-model.md
    execution-model.md
    security.md
  authoring/
    pipeline-definitions.md
    pipelines.md
    type-library.md
    examples.md
  publishing/
    publication-guide.md
    researcher-catalog.md
    schedules.md
  operations/
    install-linux-vm.md
    backup-restore.md
    upgrade-rollback.md
    task-recovery.md
    storage-management.md
  api/
    api-style.md
    errors.md
    events.md
  adr/
    0001-use-postgres-as-system-of-record.md
    0002-separate-api-worker-scheduler.md
    0003-compile-workflows-to-immutable-ir.md
```

## Documentation ownership rules

- Each doc must have an owner or owning area.
- Each doc should include `Last reviewed` and `Applies to version` metadata.
- If a feature changes a contract, the PR must update the relevant doc.
- Generated API docs should be regenerated in CI.
- Stale docs should be marked historical or deleted.
- Agent-facing prompts and context files must live under a clearly labeled `docs/ai/` or `internal/ai/` folder and must not masquerade as product architecture.

## Glossary

Create `docs/architecture/glossary.md` and enforce these terms:

- PipelineDefinition.
- PipelineRevision.
- Pipeline.
- PipelineRevision.
- Publication.
- PublicationRevision.
- Run.
- Task.
- TaskAttempt.
- Artifact.
- Workspace.
- Schedule.
- TypeDefinition.
- SavedValue.

Do not use "job" as a core internal noun in new code. If the UI says "Published Jobs" for compatibility, document that it maps to `Publication` internally.

## ADR template

Use Architecture Decision Records for durable choices.

```markdown
# ADR NNNN: Title

Date: YYYY-MM-DD
Status: Proposed | Accepted | Superseded

## Context

What problem are we solving? What constraints matter?

## Decision

What did we choose?

## Consequences

What improves? What tradeoffs remain?

## Alternatives considered

What else did we consider and why did we reject it?
```

## Authoring docs rules

Workflow and pipeline authoring docs should include:

- Minimal working example.
- Full reference.
- Validation errors and how to fix them.
- Versioning and compatibility rules.
- Examples of fan-out, dependencies, typed inputs, file inputs, and outputs.
- Anti-patterns.

## Operations docs rules

Operations docs must be command-oriented and testable. Include exact commands for:

- Starting services.
- Stopping services.
- Viewing logs.
- Running migrations.
- Backing up and restoring.
- Checking health.
- Recovering stuck tasks.

Do not rely on institutional memory for production operations.

## API docs rules

API docs must be generated from OpenAPI when possible. Hand-written docs should explain concepts, authentication, examples, and error handling rather than duplicating generated endpoint details.

## Keeping docs honest

Add CI checks:

- OpenAPI schema generation is up to date.
- Alembic migrations can build a fresh database.
- Example workflow YAML files validate.
- Example publication specs validate.
- Links in docs are checked.
- Docs mention current resource names, not deprecated internal names, except in compatibility sections.


## Review additions

> Findings below are registered with evidence, severity, and status in
> [gaps.md](gaps.md). This section says what to do about them.

### Missing required documents

The `docs/` tree omits several documents the rest of the plan depends on:

```text
docs/
  architecture/
    task-entry-point-contract.md   versioned; task images depend on it
    reference-language.md grammar, namespaces, failure rules
    configuration.md               precedence, validation, what the UI may read
    non-functional-requirements.md load, SLOs, RPO/RTO, quotas
    data-governance.md             classification, retention, deletion, egress
  operations/
    runbook-cancel-and-stuck-runs.md
    runbook-scheduler-leadership.md
    runbook-image-build-and-promote.md
    disaster-recovery.md           RPO/RTO, restore rehearsal record
  migration/
    legacy-import-guide.md         how to run importers, read reports, re-run safely
    user-migration-notes.md        what changed for admins and researchers, term mapping
  contributing.md
  security.md                      how to report a vulnerability, supported versions
  ai/                              agent-facing context, clearly labelled
```

Also add a `CHANGELOG.md` at the root with an explicit "operator actions
required" section per release - new environment variables, migrations, and image
rebuilds are the things that break an upgrade.

### The compatibility term mapping needs a user-facing home

The plan repeatedly relies on showing "Published Jobs" in the UI while the domain
says `Publication`. That mapping must exist somewhere researchers and admins can
read, not only in the developer glossary. Put it in
`docs/migration/user-migration-notes.md` and link it from the UI.

### Doc metadata should be checkable, not aspirational

`Last reviewed` and `Applies to version` are good rules, and the current project
already shows how they drift. Make them enforceable:

- Require the metadata block via a CI check that fails on a missing or malformed
  header.
- Fail CI when a document's `Last reviewed` date is older than a stated maximum
  for its category (operations runbooks should be reviewed more often than an
  ADR).
- Treat a stale runbook as a defect, because that is how the current
  documentation drift described in document 01 happened.

### Additional CI doc checks

Add to the list:

- Every ADR referenced from a document exists, and every accepted ADR is linked
  from at least one architecture document.
- The glossary contains every domain term used in the API resource names.
- Runbook commands are executed, not just linted, in the nightly compose suite
  where practical. A runbook nobody runs is a runbook that is wrong.
