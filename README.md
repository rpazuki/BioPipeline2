# BioPipeline2

A workflow platform for authoring, publishing, and running bioinformatics
pipelines. Admins author workflows and publish curated catalog entries;
researchers submit runs against immutable published revisions and retrieve the
outputs.

This is a rebuild of `bioPipeline`, not a port. The design and the reasoning
behind it live in [`migration/`](migration/); start with
[`migration/README.md`](migration/README.md) and
[`migration/gaps.md`](migration/gaps.md).

> **Status: a working vertical slice.** An admin can sign in, author a pipeline
> document, see it compile, store it as an immutable revision, submit a run
> against it, watch the tasks, and cancel — through the browser, end to end.
> What is missing is breadth, not depth: publications and the researcher
> catalog, schedules, the scheduler loop, log and artifact serving, uploads,
> and delivery to shared storage. The Phase 0b spike has been run: `make spike`
> takes a real-shaped pipeline through compile, fan-out, container execution
> and verification, and it found six unconnected seams that a green test suite
> could not see. 19 of 32 ADRs are accepted; see
> [`ASSUMPTIONS.md`](ASSUMPTIONS.md) for every place the code still assumes an
> answer.

## Quick start

Requires Python 3.12+, Docker, and GNU Make.

```bash
make setup       # create .venv, install the backend editable
make db-up       # start PostgreSQL 16 on localhost:55432
make migrate     # apply the schema
make task-image  # build the task container image
make test        # 540 tests
make worker      # run a worker against the dev database
make reaper      # run the reaper against the dev database
make api         # serve the API on localhost:8000
make openapi     # regenerate the committed contract
```

Then, to sign in and see it:

```bash
BP_SEED_ADMIN_PASSWORD='choose-something-long' make seed
make ui-setup    # install the frontend (Node 22+)
make ui          # serve the frontend on localhost:3000
```

`make test-fast` runs the domain tests alone, with no database.
`make check` runs everything CI runs for the backend: lint, format, mypy,
tests, the contract freshness gate, and the Alembic drift check.
`make ui-check` does the same for the frontend.

## What exists

| Area | Module | What it does |
| --- | --- | --- |
| Vocabulary | [`app/domain/enums.py`](backend/app/domain/enums.py) | Single source for every constrained string. The database renders each as a named CHECK constraint, so the API and the schema cannot disagree |
| Lifecycles | [`app/domain/lifecycle.py`](backend/app/domain/lifecycle.py) | Run, task, and attempt state machines with terminal-state protection and a named owning actor per transition |
| Reference language | [`app/domain/references.py`](backend/app/domain/references.py) | The `{brace}` syntax used in pipeline YAML. Reference-only interpolation — no calls, no operators, no indexing |
| Authoring | [`app/domain/authoring.py`](backend/app/domain/authoring.py) | The pipeline document: matrix, defaults, components, stages, fan-out, outputs |
| Compiler | [`app/domain/compiler.py`](backend/app/domain/compiler.py) | Document → immutable IR, or located diagnostics. Collects every error rather than raising on the first |
| IR | [`app/domain/ir.py`](backend/app/domain/ir.py) | What a run executes. Versioned, self-contained, content-hashed |
| Materialisation | [`app/domain/materialise.py`](backend/app/domain/materialise.py) | IR + submitted values → task plans. Enumerates fan-out, coerces inputs, expands dependencies |
| Application services | [`app/application/`](backend/app/application/) | Compile-and-store a revision; submit a run and its task graph atomically; release tasks whose dependencies have finished |
| Task runner | [`app/runner/`](backend/app/runner/) | Runs a whole stage inside one container, sharing a payload. Standard library only, so it imposes no dependency on a task image |
| Execution | [`app/infrastructure/execution/`](backend/app/infrastructure/execution/), [`app/workers/executor.py`](backend/app/workers/executor.py) | Launches task containers with the containment baseline; verifies declared outputs itself |
| Worker | [`app/workers/worker.py`](backend/app/workers/worker.py) | Claim, execute, record, repeat. Renews leases and watches for cancellation while a task runs; drains rather than dying on SIGTERM |
| Artifacts | [`app/infrastructure/artifacts.py`](backend/app/infrastructure/artifacts.py), [`app/application/artifacts.py`](backend/app/application/artifacts.py) | Promotes verified outputs into durable, checksummed artifacts and plans their delivery |
| Reaper | [`app/workers/reaper.py`](backend/app/workers/reaper.py) | Reclaims expired leases, converges cancellations, reaps dead workers, purges expired artifacts |
| API | [`app/api/`](backend/app/api/) | Thin routes over the services. One error envelope, request ids, cookie sessions, CSRF, cursor paging |
| Contract | [`contracts/openapi.json`](contracts/openapi.json) | Committed and checked in `make check`. Every non-browser consumer is generated from it |
| Task contract | [`app/domain/task_contract.py`](backend/app/domain/task_contract.py) | The versioned boundary between the platform and scientific code. Spec: [`docs/architecture/task-entry-point-contract.md`](docs/architecture/task-entry-point-contract.md) |
| Schema | [`app/infrastructure/db/models/`](backend/app/infrastructure/db/models/) | 32 tables, immutability triggers, resource admission control |
| Configuration | [`app/settings.py`](backend/app/settings.py) | Defaults → optional YAML → environment. Refuses to boot production with development secrets. The browser reads its share from `GET /api/v1/config`, an allowlist rather than a filtered dump |
| Fan-out | [`app/infrastructure/fanout.py`](backend/app/infrastructure/fanout.py) | Resolves a mapping file, a folder listing or a pair of globs into one task per item. Confined to allowlisted roots, because the source path is a submitted value |
| Mounts | [`app/infrastructure/mounts.py`](backend/app/infrastructure/mounts.py) | Which host paths a task container may see: attested, readable shared roots, mounted read-only at their own path |
| Spike | [`scripts/dev/spike.py`](scripts/dev/spike.py), [`examples/spike/`](examples/spike/README.md) | Phase 0b: a real-shaped pipeline from document to artifact, through real containers |
| Bindings | [`app/domain/bindings.py`](backend/app/domain/bindings.py) | Where a publication field reaches into a pipeline. Validated against the compiled IR at publish time, applied at run creation, never patching the revision (ADR 0031) |
| Publications | [`app/application/publications.py`](backend/app/application/publications.py), [`app/api/v1/catalog.py`](backend/app/api/v1/catalog.py) | The curated contract a researcher submits against: an admin chooses which values to expose and what to call them |
| Frontend | [`frontend/`](frontend/README.md) | Next.js App Router over a client generated from the committed contract. Sign-in, runs, run detail with deliveries, the pipeline editor with compiler diagnostics |

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

**The API process serves HTTP and nothing else.** No worker loop, no
scheduler, no reaper inside it. Running background work in the web process is
convenient in development and the reason the current system cannot scale past
one replica — two API processes would mean two schedulers.

**A publication binds to a stage name, not a stage key.** With a matrix, one
stage `fit` compiles into `fit:no_replicates` and `fit:replicates`; an admin
exposing "the fit stage's window" means both. Binding to a key would leave one
matrix row silently on the old value — and a run whose halves disagree says
nothing about it anywhere.

**Somebody else's run is a 404, not a 403.** Telling a caller that a resource
exists but is not theirs leaks which runs exist.

**Status fields on the wire are enumerations, not strings.** The contract is
what a client is generated from: as `str` every status is opaque and an
unhandled one renders as a blank badge nobody notices. As an enumeration, a
status added to the backend stops the frontend's build.

**An internal error is built below the CORS layer**, so a browser can actually
read it, and it carries its request id. Left to the framework's own last-resort
handler it is generated outside CORS and reaches the page as an opaque network
failure with no status, no message, and no reference — at the exact moment
somebody needs all three.

**The reaper owns the transitions no optimistic process can perform.** A
worker that died still holds tasks, and the process that would release them is
precisely the one that is gone. Every sweep is idempotent, so several reapers
may run at once and a crash mid-sweep is recovered by the next.

**Outputs are hardlinked into the artifact store, not copied.** Copying
doubles the disk cost of every run; with RNA-seq outputs in tens of gigabytes
that is the difference between a VM that works and one that fills up.
Artifacts are immutable once promoted, so sharing an inode is safe.

**Bytes first, row second.** An artifact row whose bytes are missing is a
broken download and a lie in the audit trail. A promoted file with no row is
merely disk the janitor reclaims.

**No transaction is held while a container runs.** A task can run for a day.
Each loop iteration is three short transactions — claim and commit, run
holding nothing, record and commit — because a connection open across a
day-long task would exhaust the pool and make every lease look fresh to the
reaper.

**A stage runs in one container, not one per step.** Its steps pass live
Python objects to each other — DataFrames, and a `cobra.Model` in the FBA
pipelines — so they must share a process. A step can instead return a path it
wrote, and the compiler's liveness analysis drops payload entries as soon as
nothing refers to them, so passing by path genuinely releases memory.

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

Database tests run against real PostgreSQL, and container tests against real
Docker. Both are skipped, not failed, when unavailable, so the suite still
runs on a machine with neither.

Build the task image before running the container tests:

```bash
docker build -f deploy/images/task/Dockerfile -t biopipeline2/task-base:dev .
```

Database tests are skipped, not failed, when PostgreSQL is unreachable. There is deliberately no SQLite path: the schema depends on
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

A document compiles to an immutable revision, a submission becomes a run with
its task graph, a worker drains that queue into containers, verified
outputs become retrievable artifacts, the reaper recovers whatever a dead
worker left behind, and an HTTP API exposes all of it. Remaining: the
frontend, and a delivery pass that copies outputs to shared roots. See
[`migration/09-migration-roadmap.md`](migration/09-migration-roadmap.md).
