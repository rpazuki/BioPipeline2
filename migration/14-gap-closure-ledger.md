# Gap Closure Ledger

This is the operational tracker for closing [gaps.md](gaps.md). `gaps.md` is the stable evidence register; this file is the working ledger that turns each row into either an accepted decision, implementation work, or an explicit v1 defer/drop.

## Closure rules

- `Decision needed` rows close only through an accepted ADR in [docs/adr](docs/adr/README.md). A proposed ADR stub is tracking, not closure.
- `Specified` rows close only when the referenced design change has an owner, implementation task, verification method, and either v1 scope or an explicit defer/drop decision.
- `Blocker` rows must close before the phase they block starts. For Phase 0 and Phase 1 blockers, no implementation should begin until the related ADR or implementation item is accepted.
- A row is never deleted from `gaps.md`; closure is recorded here and, for decisions, in ADRs.

## Decision-needed coverage

The following rows are covered by the ADR queue. They remain open until the ADR is accepted.

| Gap | Severity | ADR path | Current closure state |
| --- | --- | --- | --- |
| G01 | Blocker | [ADR 0001](docs/adr/0001-data-governance-and-classification.md), [ADR 0002](docs/adr/0002-ai-pipeline-designer-scope.md) | Proposed ADR exists; decision not accepted. |
| G02 | Blocker | [ADR 0003](docs/adr/0003-mcp-server-scope-and-contract.md) | Proposed ADR exists; decision not accepted. |
| G03 | High | [ADR 0004](docs/adr/0004-cli-and-notebook-client-scope.md) | Proposed ADR exists; decision not accepted. |
| G04 | Medium | [ADR 0004](docs/adr/0004-cli-and-notebook-client-scope.md) | Proposed ADR exists; decision not accepted. |
| G08 | Medium | [ADR 0021](docs/adr/0021-in-app-backup-restore-scope.md) | Proposed ADR exists; decision not accepted. |
| G09 | Medium | [ADR 0022](docs/adr/0022-ad-hoc-admin-submission-scope.md) | Proposed ADR exists; decision not accepted. |
| G10 | Medium | [ADR 0015](docs/adr/0015-recurrence-model-and-admin-recurring-jobs.md) | Proposed ADR exists; decision not accepted. |
| G11 | Medium | [ADR 0010](docs/adr/0010-configuration-strategy.md) | Proposed ADR exists; decision not accepted. |
| G12 | Low | [ADR 0014](docs/adr/0014-notifications-scope.md) | Proposed ADR exists; decision not accepted. |
| G29 | High | [ADR 0009](docs/adr/0009-tenancy-and-project-scope.md) | Proposed ADR exists; decision not accepted. |
| G35 | Medium | [ADR 0023](docs/adr/0023-task-secret-model.md) | Proposed ADR exists; decision not accepted. |
| G36 | Medium | [ADR 0012](docs/adr/0012-delete-semantics.md) | Proposed ADR exists; decision not accepted. |
| G37 | Low | [ADR 0011](docs/adr/0011-enum-representation.md) | Proposed ADR exists; decision not accepted. |
| G63 | Blocker | [ADR 0013](docs/adr/0013-shared-storage-authorization-boundary.md) | Proposed ADR exists; decision not accepted. |
| G66 | Blocker | [ADR 0001](docs/adr/0001-data-governance-and-classification.md) | Proposed ADR exists; decision not accepted. |
| G68 | High | [ADR 0007](docs/adr/0007-sso-at-launch.md), [ADR 0008](docs/adr/0008-production-runtime-and-network.md) | Proposed ADR exists; decision not accepted. |
| G69 | High | [ADR 0007](docs/adr/0007-sso-at-launch.md) | Proposed ADR exists; decision not accepted. |
| G75 | Medium | [ADR 0024](docs/adr/0024-developer-platform-parity.md) | Proposed ADR exists; decision not accepted. |
| G82 | High | [ADR 0025](docs/adr/0025-effort-ownership-calendar-and-cut-list.md) | Proposed ADR exists; decision not accepted. |
| G83 | High | [ADR 0017](docs/adr/0017-parallel-run-and-cutover-window.md) | Proposed ADR exists; decision not accepted. |
| G84 | Blocker | [ADR 0016](docs/adr/0016-representative-workflow-set.md) | Proposed ADR exists; decision not accepted. |
| G85 | Medium | [ADR 0018](docs/adr/0018-historical-run-migration.md) | Proposed ADR exists; decision not accepted. |
| G86 | Medium | [ADR 0019](docs/adr/0019-password-hash-portability.md) | Proposed ADR exists; decision not accepted. |

## Specified implementation ledger

These rows already have design text somewhere in the plan. That does not mean they are done. Each one needs an implementation owner, tracker item, and verification before the relevant phase begins.

| Gap | Severity | Scope disposition | Owner | Tracker | Verification / closure evidence | Design reference |
| --- | --- | --- | --- | --- | --- | --- |
| G05 | Medium | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [10](10-feature-parity-and-scope.md) rows 1-2, [07](07-frontend-architecture.md) missing screens |
| G06 | High | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [10](10-feature-parity-and-scope.md) row 12, [06](06-execution-and-operations.md) runtime environment images |
| G07 | High | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [10](10-feature-parity-and-scope.md) row 13, [07](07-frontend-architecture.md) missing screens |
| G13 | Medium | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [10](10-feature-parity-and-scope.md) non-goals |
| G14 | High | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [05](05-api-and-contracts.md) uploads, [04](04-data-model-postgres.md) item 8 |
| G15 | High | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [03](03-domain-model.md) source modes, [05](05-api-and-contracts.md) `url` controls, [06](06-execution-and-operations.md) security |
| G16 | High | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [03](03-domain-model.md) DeliveryPolicy, [04](04-data-model-postgres.md) item 7 (`run_deliveries`), [05](05-api-and-contracts.md) deliveries, [07](07-frontend-architecture.md) |
| G17 | High | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [13](13-open-questions.md) Q15, [09](09-migration-roadmap.md) missing importers, [04](04-data-model-postgres.md) item 3 |
| G18 | Medium | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [11](11-non-functional-requirements.md) resource governance, [06](06-execution-and-operations.md) resource governance |
| G19 | Medium | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [05](05-api-and-contracts.md) downloads |
| G20 | Blocker | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [13](13-open-questions.md) Q5, [06](06-execution-and-operations.md) task entry-point contract, [02](02-target-architecture.md) |
| G21 | Blocker | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [03](03-domain-model.md) expression language, [12](12-testing-ci-and-release.md) compiler tests |
| G22 | High | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [03](03-domain-model.md) compiled IR version |
| G23 | Medium | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [03](03-domain-model.md) immutability enforcement |
| G24 | Blocker | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [04](04-data-model-postgres.md) item 2, [06](06-execution-and-operations.md) task leases |
| G25 | High | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [04](04-data-model-postgres.md) item 3 (`schedule_fires`), [06](06-execution-and-operations.md) scheduler leadership |
| G26 | High | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [04](04-data-model-postgres.md) item 4, [05](05-api-and-contracts.md) idempotency |
| G27 | High | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [04](04-data-model-postgres.md) item 2, [06](06-execution-and-operations.md) cancellation |
| G28 | Medium | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [04](04-data-model-postgres.md) item 11, [02](02-target-architecture.md) outbox relay |
| G30 | Medium | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [04](04-data-model-postgres.md) item 5 |
| G31 | High | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [04](04-data-model-postgres.md) item 6 |
| G32 | Low | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [04](04-data-model-postgres.md) item 6 |
| G33 | Medium | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [04](04-data-model-postgres.md) item 9 |
| G34 | High | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [04](04-data-model-postgres.md) item 10, [11](11-non-functional-requirements.md) data governance |
| G38 | Medium | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [04](04-data-model-postgres.md) additional indexes |
| G39 | Medium | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [04](04-data-model-postgres.md) partitioning |
| G40 | High | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [09](09-migration-roadmap.md) importer requirements |
| G41 | High | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [05](05-api-and-contracts.md) list conventions |
| G42 | Medium | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [05](05-api-and-contracts.md) ETag / If-Match |
| G43 | High | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [05](05-api-and-contracts.md) authentication hardening |
| G44 | High | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [05](05-api-and-contracts.md) authentication hardening |
| G45 | Medium | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [05](05-api-and-contracts.md) authentication hardening |
| G46 | Medium | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [05](05-api-and-contracts.md) health and readiness |
| G47 | Medium | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [05](05-api-and-contracts.md) cancellation semantics |
| G48 | Medium | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [05](05-api-and-contracts.md) worker-facing API |
| G49 | High | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [05](05-api-and-contracts.md) contract governance, [12](12-testing-ci-and-release.md) CI pipeline |
| G50 | Medium | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [05](05-api-and-contracts.md) event stream details |
| G51 | Blocker | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [06](06-execution-and-operations.md) task leases |
| G52 | High | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [06](06-execution-and-operations.md) cancellation |
| G53 | High | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [06](06-execution-and-operations.md) orphan reconciliation |
| G54 | High | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [06](06-execution-and-operations.md) scheduler leadership |
| G55 | Medium | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [06](06-execution-and-operations.md), [04](04-data-model-postgres.md) item 3 |
| G56 | High | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [06](06-execution-and-operations.md) deployment interaction, [12](12-testing-ci-and-release.md) expand/contract |
| G57 | Medium | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [06](06-execution-and-operations.md) observability |
| G58 | Medium | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [06](06-execution-and-operations.md) observability |
| G59 | Medium | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [06](06-execution-and-operations.md) observability |
| G60 | High | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [06](06-execution-and-operations.md) backup additions, [11](11-non-functional-requirements.md) service levels |
| G61 | High | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [06](06-execution-and-operations.md) security additions |
| G62 | High | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [06](06-execution-and-operations.md) security additions |
| G64 | Blocker | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [11](11-non-functional-requirements.md) scale and load, [13](13-open-questions.md) Q6 |
| G65 | High | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [11](11-non-functional-requirements.md) service levels |
| G67 | Medium | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [11](11-non-functional-requirements.md) data governance |
| G70 | High | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [12](12-testing-ci-and-release.md) test strategy |
| G71 | High | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [12](12-testing-ci-and-release.md) CI pipeline |
| G72 | High | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [12](12-testing-ci-and-release.md) environments |
| G73 | High | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [12](12-testing-ci-and-release.md) release engineering |
| G74 | Medium | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [12](12-testing-ci-and-release.md) release engineering |
| G76 | Medium | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [12](12-testing-ci-and-release.md) seed and demo data |
| G77 | Medium | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [07](07-frontend-architecture.md) accessibility |
| G78 | Blocker | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [09](09-migration-roadmap.md) resequencing, Phase 0b spike |
| G79 | High | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [09](09-migration-roadmap.md) missing importers |
| G80 | High | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [09](09-migration-roadmap.md) importer requirements |
| G81 | High | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [09](09-migration-roadmap.md) abort criteria |
| G87 | Medium | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [08](08-documentation-guidelines.md) user migration notes, [13](13-open-questions.md) Q20 |
| G88 | Medium | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [08](08-documentation-guidelines.md) missing documents |
| G89 | Medium | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [08](08-documentation-guidelines.md) checkable metadata |
| G90 | Medium | Implement in v1 unless moved to Defer/Drop by ADR or parity ledger. | TBD | TBD | Add tests/docs or accepted defer/drop decision. | [08](08-documentation-guidelines.md) additional CI doc checks |

## Minimum gate before Phase 1

Phase 1 may start only when all of the following are true:

- Every Blocker row in `gaps.md` has either an accepted ADR or a concrete implementation task with owner and phase.
- ADRs 0001-0008, 0013, 0016, 0024, and 0025 are accepted, because they set data governance, scope, load, environment, shared-storage authorization, representative workflows, developer-platform support, and ownership boundaries.
- The specified blockers G20, G21, G24, G51, G64, and G78 have implementation tickets and acceptance tests, not just prose.
- The representative workflow set has at least a draft list, even if the final cutover list is accepted later.

## Status, 2026-09-10

Two things changed the ledger substantially: the project owner answered the
interview questions, and a real deployment's data was analysed. See
[15-premise-correction.md](15-premise-correction.md).

### Decisions

16 of 30 ADRs are accepted, including all four that the original "minimum gate"
named as Phase 1 blockers except one. **ADR 0013 (shared-storage identity)
remains the single hard blocker**, and no shared-storage access path is built
until it is answered.

The gate's other clauses are now satisfiable: G20 and G21 are implemented with
acceptance tests, G24 and G51 have schema plus tested claiming logic, G64 has
measured numbers, and G78's spike is the first item of Phase 0.

### Implemented, with tests

| Gap | Evidence |
| --- | --- |
| G20 | `app/domain/task_contract.py`, `docs/architecture/task-entry-point-contract.md`, 24 tests |
| G21 | Reformed per ADR 0027; the `${{ }}` syntax is dropped, its validation machinery reused |
| G23 | `bp_forbid_mutation` trigger on all revision tables, with a test asserting every declared table is protected |
| G24, G51 | `workers` table, lease columns, `claiming.py`, 20 tests including the two concurrency properties |
| G25 | `uq_schedule_fires_schedule_id_fire_at` |
| G26 | Partial unique index on `(requested_by, idempotency_key)` |
| G27 | Cancellation as data; `RUN_MACHINE` reserves closure to the reaper |
| G29 | `projects` + `project_members`, one default row (ADR 0009) |
| G30, G31, G32, G33, G34, G37, G38 | Constraints, indexes, snapshot-based typing, read auditing, enum policy |
| G18 | Resource admission control (ADR 0029) replaces quotas and fair-share |

### Removed from scope

`legacy_import_map` and all importer machinery (no migration), `outbox_events`
(no consumer), Podman/SELinux/Red Hat, immutable image pinning, fair-share
scheduling, per-user quotas, multi-project scoping.

### New rows

G91-G95, added to [gaps.md](gaps.md) from the real deployment analysis. G91 and
G92 are blockers: together they let a typo produce a run that reports success
and quietly did nothing, and 23% of real task specifications carry the first of
them.

### Still open

G63 (blocker), G84, G01, G02, plus the scope questions in
[13-open-questions.md](13-open-questions.md).

## Maintenance

Update this ledger when:

- An ADR moves from `Proposed` to `Accepted` or `Superseded`.
- A specified gap receives an owner or tracker item.
- A specified gap is consciously deferred or dropped.
- A new gap is added to `gaps.md`.
