# BioPipeline2

A workflow platform for authoring, publishing, and running bioinformatics
pipelines. Admins author workflows and publish curated catalog entries;
researchers submit runs against immutable published revisions and retrieve the
outputs.

This is a rebuild of `bioPipeline`, not a port. The design and the reasoning
behind it live in [`migration/`](migration/); start with
[`migration/README.md`](migration/README.md) and
[`migration/gaps.md`](migration/gaps.md).

> **Status: Phase 1, foundation.** The domain layer, the two contracts that
> blocked everything else, and the database schema exist and are tested. There
> is no API, worker, or frontend yet. All 25 ADRs are still `Proposed` — see
> [`ASSUMPTIONS.md`](ASSUMPTIONS.md) for every place the code assumes an
> answer.

## Quick start

Requires Python 3.12+, Docker, and GNU Make.

```bash
make setup      # create .venv, install the backend editable
make db-up      # start PostgreSQL 16 on localhost:55432
make migrate    # apply the schema
make test       # 133 tests
```

`make test-fast` runs the domain tests alone, with no database.
`make check` runs everything CI runs: lint, format, mypy, tests, and the
Alembic drift check.

## What exists

| Area | Module | What it does |
| --- | --- | --- |
| Vocabulary | [`app/domain/enums.py`](backend/app/domain/enums.py) | Single source for every constrained string. The database renders each as a named CHECK constraint, so the API and the schema cannot disagree |
| Lifecycles | [`app/domain/lifecycle.py`](backend/app/domain/lifecycle.py) | Run, task, and attempt state machines with terminal-state protection and a named owning actor per transition |
| Expression language | [`app/domain/expressions.py`](backend/app/domain/expressions.py) | The `${{ ... }}` syntax used in workflow YAML. Reference-only interpolation — no calls, no operators, no indexing |
| Task contract | [`app/domain/task_contract.py`](backend/app/domain/task_contract.py) | The versioned boundary between the platform and scientific code. Spec: [`docs/architecture/task-entry-point-contract.md`](docs/architecture/task-entry-point-contract.md) |
| Schema | [`app/infrastructure/db/models/`](backend/app/infrastructure/db/models/) | 36 tables, 70 foreign keys, 76 check constraints, 7 triggers |
| Configuration | [`app/settings.py`](backend/app/settings.py) | Defaults → optional YAML → environment. Refuses to boot production with development secrets |

## Design decisions worth knowing

**Anything used to run work is immutable, enforced by the database.** Revision
tables reject `UPDATE` and `DELETE` via a trigger, not by convention. A service
under deadline pressure cannot quietly bypass it.

**Tasks are held by a lease, not a claim flag.** A worker renews its lease
while it works; the reaper reclaims anything whose lease expired. Without this
a dead worker strands its task forever.

**A schedule window can only fire once**, guaranteed by a unique constraint on
`(schedule_id, fire_at)` rather than by the scheduler being careful. Two
schedulers, or one restarting at the wrong moment, cannot double-fire.

**Transitions have owners.** `cancel_requested → cancelled` belongs to the
reaper, not the worker, because the worker holding the task may already be
gone. A cancel must converge either way.

**No `expired` run status.** A run whose outputs were later cleaned still
succeeded; expiry is recorded on artifacts, not by overwriting the outcome.

## Repository layout

```
backend/
  app/
    domain/          pure models and rules; no FastAPI, SQLAlchemy, or I/O
    application/     use cases and transactions          (not written yet)
    infrastructure/  Postgres, storage, containers
    api/             thin HTTP adapters                  (not written yet)
    workers/         worker, scheduler, janitor          (not written yet)
  alembic/           migrations
  tests/
    domain/          no database required
    db/              real PostgreSQL, never SQLite
deploy/compose/      development stack
docs/                architecture, ADRs, operations
migration/           the plan, the gap register, and the ADR queue
scripts/dev/         database and migration helpers
```

## Testing

Database tests run against real PostgreSQL and are skipped, not failed, when
it is unreachable. There is deliberately no SQLite path: the schema depends on
`FOR UPDATE SKIP LOCKED`, JSONB, partial indexes, `num_nonnulls`, and plpgsql
triggers, so a SQLite fallback would silently diverge from production.

Constraint tests assert the database actually *rejects* bad rows. If a
constraint were dropped, a test fails.

## Migrations

```bash
make revision m="add widgets"   # autogenerate
make migrate                    # apply
make db-reset                   # drop the schema and rebuild from scratch
```

Two cautions the base migration already ran into:

- Alembic autogenerate does **not** emit `use_alter` foreign keys. Circular
  FKs are added by explicit statements in
  [`scripts/dev/append_base_migration_sql.py`](scripts/dev/append_base_migration_sql.py),
  and a test asserts they exist — they went missing once already.
- The constraint naming convention prepends `ck_<table>_`, so pass the short
  suffix to `CheckConstraint(name=...)`, not the full name.

## Next

Phase 2 is the walking skeleton: a minimal compiler, a one-stage workflow, run
creation, one worker, one container, one artifact, and a page that shows
status and a download link — end to end, proving every boundary while it is
still cheap to change. See
[`migration/09-migration-roadmap.md`](migration/09-migration-roadmap.md).
