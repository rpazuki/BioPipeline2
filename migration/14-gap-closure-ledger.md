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

### Still open

G84 (blocker — the representative workflow set is still unnamed, so the
acceptance criteria for the whole migration are undefined), G01, G02, plus the
scope questions in [13-open-questions.md](13-open-questions.md).

G63 is closed: ADR 0013 was accepted with Option C. G14 is closed by ADR 0033
and the work above.

## Maintenance

Update this ledger when:

- An ADR moves from `Proposed` to `Accepted` or `Superseded`.
- A specified gap receives an owner or tracker item.
- A specified gap is consciously deferred or dropped.
- A new gap is added to `gaps.md`.
