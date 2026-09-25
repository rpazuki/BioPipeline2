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
| G63 | Blocker | [ADR 0013](docs/adr/0013-shared-storage-authorization-boundary.md) | **Accepted**, Option C. Enforced by a CHECK constraint, not by convention: the database refuses to hold a `service_account` root with no attestation. Delivery to shared roots is unblocked but unwritten. |
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

### Closed by the frontend work

The frontend is built against the API rather than against the plan, which is
why building it found three things the plan and the code both claimed were
already true.

| What | Evidence |
| --- | --- |
| **G11's frontend clause was never implemented.** ADR 0010 and `settings.py` both stated that the browser reads its configuration at runtime from an endpoint built out of `Settings.public()`. There was no such endpoint, and `public()` had no caller. | `GET /api/v1/config`, `ClientConfigResponse`, and a test asserting the response model and the allowlist still agree |
| **A structurally invalid document answered 500** from both authoring endpoints. Pydantic's own error escaped `parse_document`, so the endpoint whose purpose is to say what is wrong with a document crashed on any document that was. A misspelled key is the commonest authoring mistake there is. | `pipeline_loader._located`, `compile_preview` returning structural problems as diagnostics, 4 tests |
| **An internal error was unreadable cross-origin and carried no request id.** The last-resort handler runs outside the CORS layer, so a 500 reached the browser as an opaque network failure — with nothing to trace it by, at the moment tracing matters most. | Error responses built inside the request-id middleware, below CORS; `expose_headers`; 4 tests |
| **Statuses crossed the wire as `str`.** A generated client could not know the allowed set, so an unhandled status renders as a blank badge and nothing fails. They are now enumerations in the contract, and the compile preview's inputs and stages are described rather than dumped as free-form objects. | 9 enum schemas plus `CompiledInputResponse` / `CompiledStageResponse` in `contracts/openapi.json`; exhaustive `Record<Union, Tone>` maps in the frontend |
| **G77, accessibility**, addressed rather than deferred: labelled and error-associated controls, a skip link, `aria-current`, keyboard-operable rows, `<dialog showModal()>` for focus trapping, `aria-live` status regions, a palette with contrast on both grounds. An automated axe pass and a manual audit remain. | `frontend/README.md`, component tests asserting the associations |

Phase 1's acceptance also named a seed command that did not exist; it does now
(`make seed`), and it refuses to invent a password for an administrator.

### Closed by the Phase 0b spike

Running a real-shaped pipeline end to end found eight defects: five seams that
were declared, documented, unit-tested and connected to nothing, and three
errors that only a fan-out run could expose. Each is now fixed, with a test
that fails if it comes undone. The full list, with evidence, is in
[09](09-migration-roadmap.md) under "Phase 0b, as actually run". The spike
itself passes, and asserts the scientific values rather than reporting them.

Two patterns are worth naming, because between them they account for every
finding in this build.

**A component tested in isolation cannot observe that nothing calls it.**
`Settings.public()`, `coerce_value`, `DirectoryLibraryLoader`,
`FanOutEnumerator`, `extra_mounts` and the library mount were each correct
code, with a green test, and no caller. The two checks that did catch this
class — `check_consistency.py` and the OpenAPI freshness gate — both work by
comparing one artefact against another rather than by exercising a unit.

**A fixture with one task cannot observe anything that breaks at two.** The
matrix stage key, `output_dir`, and the delivery constraint were all correct
for a single-task run and wrong for a fan-out, which is the ordinary shape of
this work. The suite had no fan-out anywhere until the spike.

G78 ("the riskiest assumptions are proven last") is closed by the spike
existing and by `make spike` keeping it runnable.

### Closed by the scheduler

**G55** (no DST or timezone resolution rule) and the open half of **Q15** (RRULE
or interval) are closed by [ADR 0015](docs/adr/0015-recurrence-model-and-admin-recurring-jobs.md),
accepted: both representations stay, RRULE is what the UI offers, and daylight
saving is resolved per schedule rather than globally.

**G25** was already closed by the `schedule_fires` unique constraint; the
scheduler is what now depends on it. The window is staked *before* any work, so
a second scheduler creates nothing rather than discovering a duplicate
afterwards, and no leader is elected — a leader that has quietly died means
nothing runs at all.

**G17** stays moot. The real deployment has 0 schedules, so nothing migrates,
and an interval schedule runs as an interval schedule for as long as it exists.

**G10** is narrowed rather than closed: a schedule covers recurring admin jobs
as the register describes them, but the register records that the concept
existed and not what those jobs did. Closing it needs somebody who has seen the
deployment, not a decision made here.

### Closed by task logs

**What a task printed is retrievable.** It was written to
`workspace/logs/attempt-N.log` and left there: `run_task_attempts.log_artifact_id`
existed with nothing setting it, `ArtifactKind.TASK_LOG` had no user, and
retention deleted the workspace. A log is now promoted for **every** outcome —
failures and timeouts most of all — and read back either from that artifact or,
while the attempt is running, from the file the container is still writing.

### Opened by task logs

**A chatty task could take a worker down.** The adapter captured the whole of a
container's stdout and stderr in memory before writing them to a file. An
aligner prints progress for hours; a task printing tens of gigabytes would have
ballooned the worker's RSS for output that was going to disk anyway. It is
streamed to the file handle now, and `test_logs_are_captured` was asserting only
that the file *existed* — which is exactly what a broken stream leaves behind,
so it now asserts the contents, against a real container.

**A size cap protects the artifact store, not the disk.** The workspace copy is
uncapped; only the promoted tail is bounded by `task_log_max_bytes`. A task that
prints a terabyte still fills the workspace volume until retention reclaims it.
Capping while streaming needs a pump thread, which is a real cost for a case
nothing has hit.

**Reading a live log assumes the API and the workers share a filesystem** — the
same assumption storage-root registration makes, and true of the single-VM
deployment ADR 0008 chose. A deployment that splits them loses the live tail and
keeps everything else, because the artifact is the durable copy.

**`attempt_count` is maintained by the claim query, not the executor.** The run
page had disabled its log button on that counter, which reads 0 for any task
executed outside the claim path — found by driving the screen. The page asks
the server whether there is a log instead of inferring it from a number another
function keeps.

### Closed by storage registration and retrieval

**G34** (read auditing) is closed to the extent it can be: every artifact read
and every refusal now writes an `artifact_access_events` row, which
`audit_artifact_reads` has defaulted to true and promised since the settings
were written. Nothing wrote a row before, because until there was a download
path there was nothing to audit.

**G63 / ADR 0013 reaches the code.** The attestation the database has been
enforcing since the first migration could only be satisfied by hand-written
SQL; there is now a service, an admin API and a screen, and the refusals the
service makes are where the reasoning lives — a path is refused if it is
relative, absent, a system directory, the platform's own storage, or an
overlap of a root that already exists.

**The artifact store as a shared root** is the refusal worth naming. Mounted
read-only into every task container, it would let any task read every other
run's outputs — through the feature that exists for reading *inputs*.

### Opened by storage registration and retrieval

**An audit row cannot share the transaction it is auditing.** A refused read
raises, the request transaction rolls back, and the row goes with it — so the
audit would have kept every success and lost every denial, which is precisely
backwards. Access events are written on their own session and committed
immediately. The same reasoning applies to any audit of a refusal, and
`audit_events` has no writer yet.

**A download's `bytes_served` is the size offered, not delivered.** A
`FileResponse` streams after the handler returns, so there is no arrangement
in which the record can depend on the transfer completing; a client that
disconnects halfway still has a row saying the whole file.

**`request.client.host` is not always an address.** It is `"testclient"` under
the test client and whatever a misconfigured proxy passes in production, and
the column is `inet` — an unparseable value turned a successful download into
a 500 until it was made NULL instead. `X-Forwarded-For` is deliberately not
honoured: without a configured list of trusted proxies it records whatever the
client asked us to.

**A directory artifact has no whole-tree download.** It is retrieved a file at
a time against the manifest the store already writes. Packaging is Phase 7
work and is the right place for it; doing it inside the process that answers
every other request is not.

### Opened by the scheduler

**A history written in one transaction cannot be ordered.** `now()` in
PostgreSQL is the transaction timestamp, so the several `schedule_events` one
tick writes all shared it, and a view sorting by time showed them in index
order — a story that did not happen. `schedule_events.created_at` now defaults
to `clock_timestamp()`. The other two event tables (`audit_events`,
`artifact_access_events`) write one row per transaction today, so they are left
alone; if either ever writes several, it has the same defect.

**Deleting a run will have to deal with its schedule history.**
`schedule_fires.run_id` and `schedule_events.run_id` have no `ON DELETE`
behaviour, so deleting a scheduled run is refused by the database. That is the
right default — an event pointing at a run that no longer exists is worse — but
whoever implements run deletion has to null these rather than discover it.

**A refusal's headline counts its problems rather than naming them.**
"Run submission rejected with 2 error(s)" is what a schedule's owner saw on the
one screen they would look at to find out why results stopped arriving. The
stored message now carries the diagnostics themselves. Found by driving the
screen in a browser, not by a test.

**A schedule cannot be moved to a newer revision of its entry.** Pinning is
deliberate, and the API and the screen both say when an entry has been
published again since — but the only way to follow it is to create a new
schedule. Repointing needs a decision about whether the stored values are
re-validated against the new revision first.

### Opened by the frontend work

**A `value` input carries no declared scalar type.** An input is public exactly
when its default is `$WILL_PROVIDE$`, so there is no default to infer a type
from, and `InputPolicy` has no field to declare one. A submitted `"4"` reaches
a science function as a string. `materialise.coerce_value` was written for this
and its docstring states the guarantee — but nothing calls it, because nothing
can supply its `target`. Closing it changes the authoring format, so it wants
an ADR rather than a quiet patch. Recorded in
[07](07-frontend-architecture.md).

### Closed by uploads

**G14 is closed.** A file reaches the platform in chunks and resumes from
whatever the server says it received, rather than from a counter this side of
the connection. The `uploads` table finally has a writer, `ArtifactKind.UPLOAD_INPUT`
a producer, and `upload_expiry_hours` a reaper sweep that releases the bytes
rather than only flipping a status column.

**The `upload` source mode now has a control behind it.** A `file` input whose
policy allows it gets a picker; the form holds `upload:<id>`, the submission
resolves it, and the worker hardlinks the artifact into the run's workspace at
the path the task spec already named. Only `url` (G15) is still a source mode
the UI has to apologise for.

**The large-input question is answered rather than deferred.**
[ADR 0033](docs/adr/0033-upload-transport-and-the-large-input-path.md): HTTP
upload is the small-file path, and a file in the tens of gigabytes belongs on a
shared root, named rather than re-transferred. Document 05 asked for a
"direct-to-storage path" for exactly this; on the single VM of ADR 0008, the
share *is* that path, and it was already built.

### Opened by uploads

**`artifacts.owner_id` was never read.** Artifact visibility was derived
entirely from the owning run, so an uploaded input — which has no run — was a
404 to the person who had just uploaded it. Both ownerships are honoured now,
and the column has a reader for the first time.

**A refusal that deletes bytes must not be rolled back.** Completing an upload
whose checksum does not match deletes the staged file and marks the upload
aborted, and that write shares the request's transaction — which the raise then
rolls back, leaving a row that says `open` over bytes that are gone. The same
trap the artifact read audit fell into, found again in the same shape: the
failure path is the one whose record matters.

**Checking the size before the offset gives the wrong refusal.** An upload that
has received everything it declared has no allowance left, so a chunk arriving
at the wrong place was answered with 413 rather than 409 — and a client resumes
on `upload.offset_conflict` and gives up on anything else. Found by driving the
real server, not by a test; the suite's uploads had no declared size, which is
the one case that cannot reach the bug.

**An expired upload's bytes had nothing to reclaim them.** The reaper marked
the row and left the staging file, which for abandoned multi-gigabyte inputs is
the whole point of the sweep.

**Nothing caps the staging area as a whole.** `upload_max_total_bytes` bounds
one upload; a user may open many, and the only thing that reclaims them is
expiry at 48 hours. A per-user quota is G18, still open.

**No client-side checksum.** `crypto.subtle` digests a whole buffer, so a
browser cannot compute one without reading the file into memory. The server's
checksum proves the bytes were stored as they arrived, not that they arrived as
they were read; closing that needs incremental hashing in a worker thread, or a
client that is not a browser.

### Closed by output delivery

**G16 is closed.** `_plan_deliveries` has written `pending` rows since
promotion was written and nothing acted on one. A courier process now carries
them: it copies a verified artifact into an attested, writable shared root,
records the path it landed at, and leaves the run's own record alone —
delivery can fail after a run has already succeeded, which is why it has its
own status, its own attempt count and its own retry.

The `POST /runs/{id}/deliveries/{id}/retry` endpoint document 05 asked for
exists, and the run page offers it on a failed row. `run_deliveries.target_path`
and `attempts` have readers for the first time.

### Opened by output delivery

**A fourth process.** The deployment runs an API, a worker, a reaper and a
scheduler; delivery is a fifth thing to keep running, and a deployment that
forgets it gets runs that succeed and outputs that never arrive — silently,
because a pending delivery looks like one that is merely early. `/ready` does
not check whether a courier is alive, and neither does anything else. That is
the same hole the scheduler and the reaper have, and it belongs to the Phase 9
operations pass.

**A pipeline can name a storage root that does not exist.** `shared_root` is
validated as a string at authoring time and resolved for the first time when
the courier tries to use it, which is after the run has succeeded. Publishing
is where the database is available and the mistake is cheap to catch; the
compiler cannot, because it is deliberately free of the database.

**Delivery writes as the service account, into a directory of the platform's
own making.** ADR 0013 permits it, and the never-overwrite rule is what keeps
it from being a way to damage a lab's existing files — but the platform still
creates directories under somebody else's share, and nothing bounds how much
it writes there. A share that fills up is the lab's problem to notice.

**Nothing cleans up after a delivery.** A delivered copy on the share outlives
the artifact it came from: retention reclaims the platform's copy and the
lab's stays, which is the point, but it also means the platform has no idea
how much of the share it is responsible for. A copy that *fails* does clean up
after itself — a forty-gigabyte transfer that runs out of disk would otherwise
leave forty gigabytes of `.report.txt.incoming-1` that nothing would ever
remove, because the next attempt writes under a new name and the platform does
not sweep storage it does not own.

### Closed by typed values

**G93 is closed.** A submission's strings are coerced against the type frozen
when the entry was published, before materialisation, so `"200"` is an `int`
in the stored task spec and a science function never receives the string.
Failures are reported per path — `values.rules.sample_size` — and all of them
at once. `materialise.coerce_value` was written for this and never called,
because nothing could supply its `target`; a frozen schema is that target.

**G33 is closed as superseded.** There is no version to resolve: a type is
frozen by snapshot at compile, at publish and at save
([ADR 0034](docs/adr/0034-where-a-type-is-declared.md)).

**`saved_values` has a writer, and `publication_fields` a type snapshot.** A
researcher keeps a filled-in rule under a name and uses it next week; one that
no longer fits the field offering it is shown disabled with the reason, because
hiding it would leave them wondering where their rule went.

### Opened by typed values

**`type_definitions` is still unwritten, now deliberately.** The real system
declares types inside the job definition and has no registry, so a CRUD screen
over that table would be a screen for something no pipeline can reference. ADR
0034 records the decision; the table stays because a curated registry is a
plausible thing to want later.

**`POST /types/import/python` is deferred to Phase 6.** Importing a type from
`labUtils.media_bot.CustomReplicateRule` means importing that module, which
means introspecting an installed environment.

**Nested structs, lists and maps coerce but do not render.** The schema and the
coercer support all three; the form shows them as JSON, because none of the
real definitions use them and a half-built repeater is worse than a box that
says what it wants.

**A field's `constraints` column is still empty.** An admin can narrow a
pipeline's type at publish time in principle — fewer enum options, a smaller
range — and nothing reads or writes it. The type is taken whole or not at all.

**The confirmation dialog rendered a typed value as JSON.** Found by driving
the form: the dialog exists so a researcher can check a day of compute before
starting it, and a line of braces is not checkable. It lists the fields now.

### Closed by environments and package management

**G06, G07 and G94 close, and Phase 6's four acceptance criteria hold.**

*An install during a running task does not affect it.* An install copies the
current generation, installs into the copy, inventories it, and only then
moves `runtime_environments.current_generation_id`. Nothing mutates a
generation, so a task that has been running for two days sees exactly what it
pinned. `environment_snapshots` — the per-run clone ADR 0028 rejected, and
which nothing ever wrote a row to — is replaced by `environment_generations`.

*A run records the package set it used.* Pinned at submission and never
re-read, shown on the run page as the environment, the count and the Python
version.

*An editable install is detected and the run marked non-reproducible.* From
pip's own `editable_project_location`, carried onto the generation and onto
every run pinning it, naming the package and the working tree.

*An admin can search installed callables and read a signature.* By importing
inside the task container, because the answer depends on what is installed
there and the API process has none of it.

**Two things make the mechanism work, and both are easy to get wrong.** Every
generation is mounted at the same container path, `/env`, because a virtualenv
embeds absolute paths and copying one to a different path would break it. And
the copy is a real copy: pip rewrites files in place, so a hardlinked clone
would corrupt the generation it came from — which is the isolation the whole
design exists for.

### Opened by environments and package management

**An install is synchronous and can take minutes.** The honest alternatives
are a fifth process to run a job queue or a request that holds a connection;
on a single VM with 5-20 users the second is the smaller cost. The operation
row is committed before the build starts, so a request that times out in a
browser still leaves a record of what was attempted — but a build that
outlives its request has no way to report its own completion.

**A lock a crashed build leaves behind needs a person.** The platform cannot
tell a dead build from a slow one, so `POST /environments/{id}/unlock` is an
administrator's judgement. Without it every later install is refused by a
build that is not running.

**Nothing reclaims an old generation.** *Closed by the generation janitor,
below.* `reference_count` was incremented when a run pinned one and
decremented nowhere, so every install was a full copy of the environment that
nothing would ever remove.

**Editable installs cannot be created through the platform**, only detected.
`check_specifier` refuses `-e /path`, because an install runs as an
administrator on the machine that runs everybody's work and a path in that box
is an install nobody reviewed. Somebody who needs one does it on the host; the
platform then detects and reports it.

**ADR 0028's feasibility list is still only partly discharged.** Isolation
during a concurrent install, native extensions, and the exact production image
are exercised by the tests here against real containers. Generation garbage
collection is built (below); disk growth on a real environment is still
unmeasured, and the ADR asked for a number.

**Listing importable modules had to be narrowed to site-packages.** Found by
driving the screen: the first version answered "what can I call?" with the
whole standard library, putting `antigravity` in front of an author looking
for the library an admin installed for them.

### Closed by the administrative surface

**`audit_events` has a writer.** The longest-standing empty seam in the
schema: it has been there since the base migration, and everything it was for
happened anyway — somebody published an entry, attested a root, installed a
package, changed a colleague's role — with only the effect left behind.
Fourteen actions write to it now, and every one of them has a writer, because
a vocabulary that advertises more than it records is the antipattern this
project keeps closing.

**The rule is the mirror of the read audit, and both are deliberate.** A
mutation's record shares the transaction of the change it describes: if the
change rolls back, the record goes with it, because a row saying a root was
revoked when it was not is the one people will believe. A read *refusal* is
written on a session of its own, because the request it refused is about to
roll back. Same principle underneath — the record shares the fate of the thing
it describes.

**A deployment can add a person without shell access.** The only route was
`scripts/dev/seed.py` on the server. The platform generates the password, the
administrator sees it once, and `must_change_password` means the only request
that session may make is the one that replaces it — so an account an admin
created is not an account an admin can go on signing into. G45 closes with it:
reset, role change and deactivation all bump the session epoch, which ends
outstanding sessions on their next request.

**The fleet is visible.** `workers` had a heartbeat nothing displayed, so a
worker that had quietly stopped looked exactly like a long queue.

### Opened by the administrative surface

**The audit records shared authority, not everything.** Accounts, roles,
storage roots, the catalog, the environment. A run and a schedule are absent
on purpose — each already records who cancelled or paused it, on the row — but
that is a boundary somebody has to be told, or the log looks incomplete rather
than scoped.

**The audit has no retention.** It grows for ever and nothing prunes it, which
is right for an audit and wrong for a disk. ADR 0001 governs how long it has
to be kept, and that ADR is amended rather than fully answered.

**The user list was unpaged until the screen made it obvious.** Found by
driving: the development database had 8,336 accounts, 7,823 of them left by
the test suite, and the screen rendered all of them. The endpoint is paged and
searchable now, and the API conftest deletes the accounts a test created where
nothing references them — 4,541 went. The rest own pipelines, and a pipeline
revision is immutable by design, so their authors stay.

**Nothing verifies a deactivated user's running work.** Their access ends
immediately; a run of theirs that is executing carries on to completion. That
is probably right — killing work because somebody left is its own kind of
damage — but it is not a decision anybody has made.

### Closed by the generation janitor

**A generation nothing can reach is reclaimed.** ADR 0028 asked for it —
"unreferenced generations are garbage-collected after a retention period" —
and the schema carried a `reference_count` column for it that submission
incremented and nothing decremented. The column is gone rather than repaired.
It was the wrong shape: decrementing one means some process writing "this run
is over" separately from the run ending, and a process that dies in between
leaves a generation nothing will ever reclaim and nothing that would ever say
so. The references *are* the runs, so `reclaimable` asks the runs — no live
run pinned it, it is not what the next submission would pin, and it was built
longer ago than the grace period.

**What is reclaimed is the directory, not the row.**
`environment_generations.purged_at` is `artifacts.purged_at` (ADR 0012): the
bytes go, the record stays, and `packages` still answers what the runs that
pinned it imported. A run's provenance does not expire with the disk it used.

**The grace period is not tuning.** Submission reads the environment's pointer
and commits the run a moment later, and inside that moment no row references
the generation the run is about to pin. A day of grace closes that window
without a lock, and leaves an administrator a day to look at what an install
replaced. `BP_ENVIRONMENT_GENERATION_GRACE_HOURS`.

**A path outside the environment root is refused, not removed.** The path
comes out of a database row, and a sweep that will remove whatever a row names
is one edited column away from removing something that was never a
generation. The refusal is logged and the row is left alone, so nothing claims
disk was reclaimed that was not.

**A failed first build now cleans up after itself.** `create_environment` left
its half-built directory behind when the build failed, and the row it belonged
to records no path — so nothing could ever have reclaimed it. Found while
writing the sweep, which can only remove what a row points at.

**The generations list has a screen.** The endpoint existed and the client
function existed; nothing called either. It is now the place an admin can see
which builds still exist on disk and which were reclaimed, which is also the
only way the janitor's work is visible.

### Opened by the generation janitor

**Nothing reclaims a directory no row points at.** The sweep removes what rows
name. A directory left by a build that failed before it recorded a path, or by
a version of this code that is no longer running, is invisible to it.
Reconciling the environment root against the table is the Phase 9
database-versus-artifact reconciliation question in miniature, and is not
built.

**A reclaimed generation cannot be brought back.** `packages` records what was
in it, and for a non-editable generation that is enough to build the same set
again, but nothing offers to. An administrator who wanted back what the
janitor removed reinstalls by hand.

**Audit retention is still unbuilt**, and is a different question: ADR 0001
leaves "retention and redaction rules for parameters and logs" to define
before v1 ships, and `audit_events` grows for ever until it is defined.

### Closed by operations hardening

**A deployment can be installed from a document.**
[docs/operations/deployment.md](../docs/operations/deployment.md) walks a
clean Ubuntu VM to a working platform, with the systemd units it refers to in
`deploy/systemd/` and a configuration template beside them. The units carry
the two decisions that are easy to get wrong: the worker's stop timeout is
twelve hours, because a worker drains rather than dying and a task can run for
days; and every process is confined to `/var/lib/biopipeline2`, so a storage
root outside it has to be granted deliberately.

**Storage drift is checked by code.** `scripts/ops/reconcile.py` compares
`artifacts`, `environment_generations` and `workspaces` against the disks they
name, and a weekly timer runs it. `--reclaim` removes the waste and writes
nothing to the database: an operator freeing disk must not also be rewriting
the record of what happened.

**The acceptance criterion had to be corrected to be true.** Document 09 asked
for a reconciliation "reporting zero orphans". Those are two different
findings. A row whose bytes are gone is a broken download; a directory nothing
points at is disk. The only safe backup order is database first and artifacts
second — the other order dumps rows naming bytes the copy never reached — and
that order *produces* orphans. A drill reporting none would mean the backup
was taken the dangerous way round. The criterion is zero **missing**.

**Draining became visible.** The worker has stopped claiming on SIGTERM since
Phase 4, but its row said `active` until the process exited, so during an
upgrade a worker that was busy and a worker that was leaving looked identical.
The heartbeat writes `draining` now. The signal handler still only sets a
flag: a handler that writes to the database is how a deployment becomes a
deadlock.

**Logs were JSON-shaped rather than JSON.** Every process built its line by
`%`-substitution into a JSON-looking format string, so a message containing a
quote — a filename, pip's own words, a stack trace — produced a line no parser
would accept. Logs are read on the worst day of a deployment's life, which is
exactly the day a message has quotes in it. One formatter now serialises
properly and carries `request_id`, `run_id`, `task_id`, `worker_id` and
`schedule_id` as fields rather than inside sentences.

**Metrics are the numbers somebody would be woken for**, computed on request
rather than scraped: `GET /api/v1/admin/metrics`, rendered by the Admin
screen's "Right now" panel with the thresholds applied. Prometheus was
declined on the same grounds as everything else at this scale — a metrics
stack would be more operational surface than the platform it watches.

**Two failures are only visible here.** A schedule whose firing time passed
and stayed passed, because a dead scheduler's symptom is a run that does not
exist; and the age of the oldest queued task, because queue depth cannot tell
a busy afternoon from nothing claiming at all.

### Opened by operations hardening

**The three acceptance rehearsals are not done.** An install followed end to
end on a clean VM, a restore proved by the reconciliation, and an upgrade with
a day-long task running through it. None can be discharged from a development
machine, and until they are, the documentation is a claim rather than a
result.

**No production container image.** The deployment runs from a virtualenv and a
standalone Next build under systemd. That is honest for a single lab VM and it
means upgrades are `git checkout` plus `pip install`, with no image to roll
back to.

**Nothing watches the database itself.** PostgreSQL's own health is left to
whatever the institution already runs.

### Closed by the response to evaluation 1

[Evaluation 1](eval_1.md) reviewed the implementation in September 2026 and
found two false guarantees and two lifecycle defects. All four are closed,
each with the test that reproduces it.

**E1-01: two workers could jointly overcommit the host.** The budget is an
*aggregate* predicate and a row lock cannot protect one: two claim
transactions each computed what was committed from their own snapshot, in
which the other's claim did not exist, and `SKIP LOCKED` was deliberately
sending them at different rows. Both passed the same check and both
committed. Reproduced here before it was fixed -- two claimers, two
full-budget tasks, both claimed -- and closed by serialising admission on an
advisory lock. The lock is *tried*, not waited for: a worker that finds
another claim in flight backs off, which is already what "nothing fits"
means, and waiting would let any caller holding a claim transaction open
deadlock the queue.

**E1-02: researchers could bypass the publication contract.** `POST /runs`
took any revision id from any signed-in user, which made the catalog a
suggestion: a revision id appears in the metadata of every run, so anyone
holding one could run an unpublished or withdrawn revision with values no
publication would have allowed. It is admin-only now -- an author has to be
able to run what they just wrote -- and such a run records
`requested_from = 'admin'`, so "which runs bypassed a publication" is a
question the row can answer. ADR 0022 remains open on whether it should
exist at all; until it is decided, the narrower answer is the safe one.

**E1-03: a cancelled task was recorded as a failure.** The adapter reported
`cancelled=False` always, and every non-timeout failure became `failed`.
Docker cannot tell the difference -- a cancelled container, a container
killed because the lease was lost, and a crash are all a non-zero exit -- so
the reason now travels from the worker, which is the only thing that knows
it. `StopSignal` carries *why*, and a cancellation is recorded as a
cancellation.

**E1-04: a worker that lost its lease could overwrite its successor.** The
final write was `WHERE id = :task`, with no ownership condition, so a worker
finishing a container after the reaper requeued its task could mark the new
owner's task terminal and clear its lease. Every worker-owned finalisation is
now a compare-and-set on `claimed_by` *and* `attempt_count`, and a worker
that finds it changed no rows writes nothing further: no task status, no
dependants released, no run advanced. A lease-lost attempt returns before
promotion, so its outputs cannot become the winning result.

**Decision status was made honest.** Seven records that the code already
assumes -- ADRs 0008, 0013, 0015, 0031, 0032, 0033, 0034 -- were marked
`Accepted` under the owner's name with no approval recorded anywhere. They
are now `Implemented proposal - pending ratification`, each saying what is
already built on it, which is the cost of reversing it. The ADR index, the
README and `ASSUMPTIONS.md` agree on the new counts, and
`check_consistency.py` now compares every ADR's own status against the
section of the index listing it -- the check that would have caught this.

**The spike stops when it is finished.** It counted loop *iterations*, and an
idle iteration is a sleep whose backoff grows to thirty seconds, so it went
on sleeping for minutes after proving its point. It now stops when its run is
terminal, with a wall-clock deadline as the bound.

**Two test-harness bugs that had been hiding pollution.** A teardown cleared
`claimed_by` on rows that were still claimed, which the `held task has a
lease` CHECK refuses -- so the teardown raised, left its rows behind, and
every later budget test failed on arithmetic that included them. And the API
cleanup deleted artifacts before attempts, which the attempt-to-log foreign
key refuses; artifacts and attempts point at each other, so the loop has to
be cut before either is deleted.

### Still open from evaluation 1

**E1-05, the decision review, is the owner's.** Seven ADRs await
ratification; the remaining fifteen "accepted" ones have no recorded approval
event either, and none was audited here.

**E1-06: the representative workflow set.** Still one converted pipeline
(`examples/pipelines/`), still ADR 0016 unanswered. This is the same blocker
as G84 and it governs whether the compiler and the schema are shaped around
one family by accident.

**E1-07: there is no CI.** Every gate is a command somebody has to remember.

**E1-08: shared-storage mounts are global, not project-scoped.** Safe under
the single-project assumption (ADR 0009) and dangerous the moment projects
are enabled, which is exactly when nobody will remember. The worker also
caches the mount set at startup, so a revoked root stays mounted until it
restarts.

**E1-10: live-derived fixtures and the production OS.** 24 YAML and job
definitions copied from the deployment are still tracked, with lab labels and
institutional share paths, and removing them from the tree would not remove
them from history. The deployment guide is written for Ubuntu while the
expected target is Red Hat (ADR 0008, now pending ratification).

### Still open

G84 (blocker — the representative workflow set is still unnamed, so the
acceptance criteria for the whole migration are undefined), G01, G02, plus the
scope questions in [13-open-questions.md](13-open-questions.md).

G63 is closed: ADR 0013 was accepted with Option C. G14 is closed by ADR 0033
and the work above, G16 by the delivery pass, G93 and G33 by typed values, and
G06, G07 and G94 by environments.

## Maintenance

Update this ledger when:

- An ADR moves from `Proposed` to `Accepted` or `Superseded`.
- A specified gap receives an owner or tracker item.
- A specified gap is consciously deferred or dropped.
- A new gap is added to `gaps.md`.
