# Gaps

Consolidated register of every gap found reviewing documents 01-09 against the
`bioPipeline` source tree on 2026-09-10.

Documents 10-13 and the `Review additions` sections appended to 01-09 contain the
proposed fixes. This document is the index: one row per gap, what it is, how it
was verified, how bad it is, and where it is now addressed. Use it as the
checklist that closes before Phase 1, not as a second copy of the analysis.

This file is now the authoritative closure checklist for the migration plan. The
working tracker is [14-gap-closure-ledger.md](14-gap-closure-ledger.md), and the
decision queue is under [docs/adr](docs/adr/README.md). Proposed ADR files count
as tracking; only accepted or superseded ADRs count as closure.

## Status, 2026-09-10

The register is still the evidence record, but interviewing the project owner
and analysing a real deployment changed the disposition of many rows. See
[15-premise-correction.md](15-premise-correction.md).

**Void — the row rested on a wrong premise:**
G66 (data governance tiers), G67 (retention obligations), and most of G64's
framing. The platform holds no data corpus.

**Moot — no migration is happening:**
G17, G40, G79, G80, G83 (reduced), G85, G86.

**Reversed — the row's recommendation was wrong:**
G06 (immutable images were the wrong replacement for package installs),
G21 (the `${{ }}` language was invented, not discovered), and document 01's
condemnation of published-field bindings.

**Narrowed:**
G61, G62 (container hardening: code is trusted, input is not — ADR 0030),
G18 (resource admission control replaces quotas and fair-share),
G29 (single project), G28 (outbox dropped rather than given a consumer).

**Closed by implementation, with tests:**
G20, G21 (rewritten form), G23, G24, G25, G26, G27, G30, G31, G32, G33, G34,
G37, G38, G51, G55.

**Closed since:** G63 — ADR 0013 accepted (Option C: service account, with a
root exposed only when every user reaching it already has equivalent access,
enforced by an attestation constraint). G55 — ADR 0015 accepted, with a DST
rule per schedule and a scheduler that implements it.

**Still blocking:** G84 (day-one pipeline set), G01 and G02 (AI Designer and
MCP scope).

**New, found in the real data and not in the original register:**

| ID | Gap | Severity |
| --- | --- | --- |
| G91 | An unresolvable template reference is passed through as a raw mapping instead of raising. 509 of 2,178 real task specifications (23%) carry one. | Blocker |
| G92 | A `process_arg_mapping` override naming a step absent from the target pipeline is silently dropped. Combined with G91, a typo produces a successful run that quietly did nothing. | Blocker |
| G93 | Typed values are submitted as strings and never coerced (`"n_samples": "200"` against a type declaring integer). | High |
| G94 | Environment snapshots cannot capture editable installs, which the real install history uses. Reproducibility is claimed but not delivered. | High |
| G95 | Failed runs are deleted by hand to keep the list readable, destroying the evidence needed to diagnose intermittent failures. The UI must make failures filterable instead. | Medium |

## How to read this

**Severity**

| Level | Meaning |
| --- | --- |
| Blocker | Cannot start the phase it belongs to without an answer. Wrong answers invalidate work already done. |
| High | Will surface as a production incident, a user-visible regression, or a failed cutover. |
| Medium | Costs rework or degrades the product; survivable if consciously accepted. |
| Low | Worth fixing while the cost is near zero. |

**Status**

- `Open` - no decision recorded anywhere.
- `Specified` - a fix is written into the plan; still needs implementing.
- `Decision needed` - the plan describes the options; a person must choose.

**Evidence** cites the current repository, so each claim is checkable rather than
asserted. Paths are relative to the `bioPipeline` repository root.

---

## A. Scope was never enumerated

Documents 01-09 read as complete but never inventory the existing feature
surface. These subsystems exist in the current repository and appear in none of
them. Silence reads as a decision to drop; none of these were decisions.

| ID | Gap | Evidence | Severity | Status | Addressed in |
| --- | --- | --- | --- | --- | --- |
| G01 | **AI Pipeline Designer** absent from the plan entirely - no bounded context, tables, API, UI, or roadmap phase. A multi-provider tool loop with per-turn iteration and wall-clock budgets and server-side-only keys. | `src/bio_pipeline_manager/ai_agent.py`, `ai_providers.py`, `ai_tools.py`, `ai_schema_provider.py`; `backend/app/api/routes/ai_chat.py`; `frontend/src/app/ai-chat/`; `configs/app_config.yaml` (`backend.shared.ai`) | Blocker | Decision needed | [10](10-feature-parity-and-scope.md) row 16, [13](13-open-questions.md) Q2, [02](02-target-architecture.md) missing contexts |
| G02 | **MCP server absent.** 74 tool registrations mirror `/api/v1` routes by hand across two transports. The plan's rename of `published-jobs` to `publications` breaks all of them, and the plan never notices. | `mcp/bio_pipeline_mcp/server.py` (74 tool registrations), `http_server.py`, `client.py`; separate `pyproject.toml` | Blocker | Decision needed | [10](10-feature-parity-and-scope.md) row 17, [13](13-open-questions.md) Q3, [05](05-api-and-contracts.md) contract governance |
| G03 | **CLI absent.** Also the only path that creates the first admin user (`auth bootstrap-admin`), so some CLI is mandatory whatever else is decided. | `src/bio_pipeline_manager/cli.py:20` (`main`), subcommands from line 25 | High | Decision needed | [10](10-feature-parity-and-scope.md) row 18, [13](13-open-questions.md) Q4, [02](02-target-architecture.md) missing consumers |
| G04 | **Python / notebook client absent**, along with the legacy standalone `create_app` it depends on. | `src/bio_pipeline_manager/client.py`, `src/bio_pipeline_manager/api/app.py` | Medium | Decision needed | [10](10-feature-parity-and-scope.md) row 19, [13](13-open-questions.md) Q4 |
| G05 | **Template galleries absent** for both pipelines and job definitions. The new plan offers a blank YAML editor in their place. | `src/bio_pipeline_manager/templates.py`, `job_definition_templates.py`; routes `/templates`, `/job-definition-templates` | Medium | Specified | [10](10-feature-parity-and-scope.md) rows 1-2, [07](07-frontend-architecture.md) missing screens |
| G06 | **UI package install/uninstall removed silently.** Immutable runtime images are the right call, but the plan deletes a live admin capability with no replacement workflow: no image definition, build, promotion, or rollback story, and the production VM may have no outbound network to build on. | `src/bio_pipeline_manager/packages.py`, `installs.sqlite`, route `/packages`, page `frontend/src/app/environment/` | High | Specified | [10](10-feature-parity-and-scope.md) row 12, [06](06-execution-and-operations.md) runtime environment images |
| G07 | **Package introspection absent.** Listing and searching installed functions and classes and reading signatures is how an admin discovers callable science functions. Without it the authoring UX loses its discovery step. | `src/bio_pipeline_manager/package_introspect.py`; `/packages/inspect`, `/search`, `/signature` | High | Specified | [10](10-feature-parity-and-scope.md) row 13, [07](07-frontend-architecture.md) missing screens |
| G08 | **In-app backup/restore absent** from the plan as a feature; only an ops runbook and one endpoint. With Postgres plus an artifact volume its semantics change and are undefined. | `src/bio_pipeline_manager/backup.py`, route `/backup`, page `frontend/src/app/backup/` | Medium | Decision needed | [10](10-feature-parity-and-scope.md) row 14 |
| G09 | **Ad-hoc admin task submission has no successor.** The one-off job queue and submit page are not in the new model, and nothing says whether that is deliberate. | `src/bio_pipeline_manager/job_queue.py`, `runner.py`, route `/jobs`, page `frontend/src/app/submit/` | Medium | Decision needed | [10](10-feature-parity-and-scope.md) row 3 |
| G10 | **Recurring admin jobs have no successor concept** at all, distinct from researcher schedules. Narrowed by ADR [0015](docs/adr/0015-recurrence-model-and-admin-recurring-jobs.md): a schedule already covers the shape as described — stored values submitted on a recurrence, owned by an admin — so the open question is only whether those jobs ran something *other* than a published pipeline. The register records that the concept exists and not what it did; somebody who has seen the deployment must say. | `src/bio_pipeline_manager/recurring_job.py` | Medium | Decision needed | [10](10-feature-parity-and-scope.md) row 11, [09](09-migration-roadmap.md) missing importers |
| G11 | **Config strategy undefined.** The current system has one `app_config.yaml` with environment profiles shared by frontend and backend; the plan mentions only `.env` and `settings.py`. No precedence, boot validation, secret separation, or statement of which values the frontend may read. | `configs/app_config.yaml` | Medium | Decision needed | [10](10-feature-parity-and-scope.md) row 21, [13](13-open-questions.md) Q10, [02](02-target-architecture.md) configuration strategy |
| G12 | **Notifications are half-present.** Document 02 lists an "email" infrastructure adapter; nothing else in the plan sends anything, and the current system has no email at all. Long runs finishing unannounced is a real usability gap. | No implementation in `src/` or `backend/` | Low | Decision needed | [10](10-feature-parity-and-scope.md) row 23, [13](13-open-questions.md) Q14 |
| G13 | **No explicit non-goals.** Without them the ledger cannot resist scope creep during a rebuild that is already large. | - | Medium | Specified | [10](10-feature-parity-and-scope.md) non-goals |

---

## B. Silent feature regressions

Each of these is implemented today and cannot be expressed in the plan's
contracts. They would have shipped as regressions.

| ID | Gap | Evidence | Severity | Status | Addressed in |
| --- | --- | --- | --- | --- | --- |
| G14 | **Chunked / resumable upload lost.** The plan has a single `POST /files/uploads`. Not workable for multi-gigabyte genomics inputs, and no `uploads` table can represent an upload in progress. | `backend/app/api/routes/published_jobs.py:361-389` (offset-append streaming); `backend/tests/test_published_jobs_routes.py:591` | High | Specified | [05](05-api-and-contracts.md) uploads, [04](04-data-model-postgres.md) item 8 |
| G15 | **`url` input source mode lost.** The plan lists only `upload` and `shared`. The current system fetches a researcher-supplied URL server-side - which is also an unguarded SSRF surface that the plan never hardens. | `src/bio_pipeline_manager/published_jobs.py:15`, `:46`, `:623-631` (`urlopen`, 30s timeout, 1 MiB chunks) | High | Specified | [03](03-domain-model.md) source modes, [05](05-api-and-contracts.md) `url` controls, [06](06-execution-and-operations.md) security |
| G16 | **Output delivery to shared storage lost.** The reaper copies outputs whose field declares `delivery: ["shared"]` into an allowlisted root. The plan models input `source_policy` and has no output destination concept anywhere - no domain term, no table, no endpoint, no UI. Delivery can fail after a run succeeds, so it needs its own state and retry. | `src/bio_pipeline_manager/run_reaper.py:4`, `:146`, `:156` | High | Specified | [03](03-domain-model.md) DeliveryPolicy, [04](04-data-model-postgres.md) item 7 (`run_deliveries`), [05](05-api-and-contracts.md) deliveries, [07](07-frontend-architecture.md) |
| G17 | **Recurrence model changes with no migration path.** Current schedules are interval-based ("every N units"); the plan proposes RRULE. No mapping, no DST policy, and no schedule importer in Phase 8. A schedule that silently fails to migrate means work stops happening and nobody notices. | `src/bio_pipeline_manager/recurring_schedule.py:45-47` (`interval_delta`) | High | Specified | [13](13-open-questions.md) Q15, [09](09-migration-roadmap.md) missing importers, [04](04-data-model-postgres.md) item 3 |
| G18 | **Quota exists only per run.** The plan carries `workspaces.quota_bytes` but has no per-user or global quota, and no fair-share policy - one 500-task fan-out can starve every other researcher on a shared VM. | `src/bio_pipeline_manager/run_workspace.py:66-69` (`max_bytes`) | Medium | Specified | [11](11-non-functional-requirements.md) resource governance, [06](06-execution-and-operations.md) resource governance |
| G19 | **Range requests on artifact download unspecified.** Resuming a large download over a campus VPN is the normal case. | - | Medium | Specified | [05](05-api-and-contracts.md) downloads |

---

## C. Design blockers

Two contracts the plan depends on but never writes. Both block Phase 2.

| ID | Gap | Evidence | Severity | Status | Addressed in |
| --- | --- | --- | --- | --- | --- |
| G20 | **Task entry-point contract missing.** The plan keeps science packages external (YAML names `labUtils.*` callables, imported in-process today) *and* moves execution into containers, but never says how a workflow names a callable across that boundary: invocation, parameter marshalling, output declaration and discovery, failure signalling, or what the container may assume. Blocks the compiler and the execution adapter simultaneously. | `src/pipeline/engine.py`; current subprocess convention `python -m bio_pipeline_manager.run_task TASK.json` | Blocker | Specified | [13](13-open-questions.md) Q5, [06](06-execution-and-operations.md) task entry-point contract, [02](02-target-architecture.md) |
| G21 | **Expression language unspecified.** The example workflow uses `${{ inputs.x }}`, `${{ stages.a.outputs.b }}`, `${{ fanout.item.path }}`. That is a language, evaluated over admin-authored text and researcher-supplied values, with no grammar, namespace rules, type rules, escaping, evaluation timing, or failure mode. Silent empty substitution into a path parameter is how traversal happens. Phase 2's acceptance criteria do not test it. | [03](03-domain-model.md) workflow authoring example | Blocker | Specified | [03](03-domain-model.md) expression language, [12](12-testing-ci-and-release.md) compiler tests |
| G22 | **Compiled IR has no version.** The IR is immutable and read by later releases. No `ir_version` and no compatibility policy, so the first breaking IR change either breaks in-flight runs or forces recompiling immutable revisions - contradicting the plan's central principle. | [03](03-domain-model.md), [04](04-data-model-postgres.md) `compiled_spec` | High | Specified | [03](03-domain-model.md) compiled IR version |
| G23 | **Immutability is asserted, not enforced.** "Anything used to run work is immutable" is load-bearing for the whole design, with no stated mechanism. | [03](03-domain-model.md) versioning model | Medium | Specified | [03](03-domain-model.md) immutability enforcement |

---

## D. Data model defects

| ID | Gap | Severity | Status | Addressed in |
| --- | --- | --- | --- | --- |
| G24 | **No worker lease or heartbeat table.** Document 06 promises "a small heartbeat table" and stale-claim detection; document 04 has neither, and `run_tasks` has a `claimed_by` flag rather than a lease. A worker that dies mid-task strands its task in `claimed` forever. No poison-task limit, and no orphan-container reconciliation. | Blocker | Specified | [04](04-data-model-postgres.md) item 2, [06](06-execution-and-operations.md) task leases |
| G25 | **Schedule firing is not idempotent.** Document 06 requires one run per due event and document 09 accepts "once and only once", but `schedules` has no key that makes a duplicate fire impossible. Locking does not survive a scheduler restart at the wrong moment. Also missing: `catchup_policy`, `overlap_policy`, `max_concurrent_runs`, `end_at`, DST resolution. | High | Specified | [04](04-data-model-postgres.md) item 3 (`schedule_fires`), [06](06-execution-and-operations.md) scheduler leadership |
| G26 | **Run submission is not idempotent.** No idempotency key. A double-clicked submit or a retried request creates a second run - expensive when a run occupies a shared compute node. | High | Specified | [04](04-data-model-postgres.md) item 4, [05](05-api-and-contracts.md) idempotency |
| G27 | **Cancellation has no data model.** `cancel_requested` is a status with no `cancel_requested_at`, no requester, and no way for a worker to learn of it. | High | Specified | [04](04-data-model-postgres.md) item 2, [06](06-execution-and-operations.md) cancellation |
| G28 | **`outbox_events` has no consumer.** No process in document 02 drains it. An unread outbox is a table that only grows. | Medium | Specified | [04](04-data-model-postgres.md) item 11, [02](02-target-architecture.md) outbox relay |
| G29 | **Tenancy is half-applied.** Persistence rule 8 requires tenant/project columns; no `projects` table exists, no table carries `project_id`, and no API route or index scopes by it. | High | Decision needed | [04](04-data-model-postgres.md) item 1, [13](13-open-questions.md) Q9 |
| G30 | **`runs.workspace_id` and `workspaces.run_id` are circular**, with no FK on the former and no uniqueness on the latter. Document 06 also says a workspace serves "one run **or** task" without deciding which. | Medium | Specified | [04](04-data-model-postgres.md) item 5 |
| G31 | **Missing constraints**: exactly-one-of on `publication_fields` input/output refs; `fixed_value` implies hidden; FK and ownership check on `publications.current_revision_id`; unique `(storage_backend, storage_key)` on `artifacts` (two rows over the same bytes will let the janitor delete live data); attempt attribution on artifacts; dependency cycle guard. | High | Specified | [04](04-data-model-postgres.md) item 6 |
| G32 | **`sessions` cannot express sliding renewal.** No `last_seen_at`, although the current system renews sessions on use. | Low | Specified | [04](04-data-model-postgres.md) item 6 |
| G33 | **Type version resolution is ambiguous.** `saved_values.type_version` is nullable with no defined resolution rule and no current-version pointer on `type_definitions`. | Medium | Specified | [04](04-data-model-postgres.md) item 9 |
| G34 | **No read auditing.** `audit_events` covers mutations; artifact *download* is not audited. Mandatory for regulated data, and high-volume enough to need its own table. | High | Closed | `artifact_access_events` has its own table, and every download, metadata read and refusal writes one — on its own transaction, because a refusal raises and would otherwise be rolled back with the request it refused. `audit_events` (mutations) still has no writer |
| G35 | **No secret model.** Nowhere to put credentials a task needs for an external service, and no assertion that tasks never need them. | Medium | Decision needed | [04](04-data-model-postgres.md) item 12, [06](06-execution-and-operations.md) security |
| G36 | **Delete semantics undefined.** `DELETE /runs/{id}`, an `expired` status, and `deleted_at` columns coexist with no stated soft-versus-hard rule - which also decides whether "verifiable deletion" is possible while backups exist. | Medium | Decision needed | [13](13-open-questions.md) Q12, [11](11-non-functional-requirements.md) |
| G37 | **Inconsistent enum representation**: some columns use `text check in (...)`, most use bare `text`, for the same kind of field. No single source shared with the Pydantic models. | Low | Decision needed | [04](04-data-model-postgres.md) enum policy, [13](13-open-questions.md) Q11 |
| G38 | **Missing indexes** for lease reaping, retry pickup, janitor expiry scans, abandoned uploads, session pruning, outbox draining, schedule fires, deliveries, and catalog text search - document 07 specifies catalog search and nothing supports it. | Medium | Specified | [04](04-data-model-postgres.md) additional indexes |
| G39 | **No partitioning or growth decision** for `run_tasks`, `run_task_attempts`, `artifacts`, `audit_events`, and the download log. Retrofitting onto a large live table is painful. | Medium | Specified | [04](04-data-model-postgres.md) partitioning |
| G40 | **No `legacy_ref` mapping**, so no importer can be re-run idempotently. | High | Specified | [09](09-migration-roadmap.md) importer requirements |

---

## E. API and contract gaps

| ID | Gap | Severity | Status | Addressed in |
| --- | --- | --- | --- | --- |
| G41 | **No pagination, sorting, or filtering convention**, and no list envelope shape - while document 07 assumes query keys "by feature, filters, page, and sort". | High | Specified | [05](05-api-and-contracts.md) list conventions |
| G42 | **No optimistic concurrency.** The error model reserves `409` for a stale revision, but nothing carries a version. Two admins editing one publication silently overwrite. | Medium | Specified | [05](05-api-and-contracts.md) ETag / If-Match |
| G43 | **No CSRF strategy** for a cookie-authenticated API with state-changing requests - and document 07 puts the frontend on a separate origin in development, which is exactly the case that breaks naive assumptions. | High | Specified | [05](05-api-and-contracts.md) authentication hardening |
| G44 | **No login rate limiting or lockout policy**, so each deployment invents one. | High | Specified | [05](05-api-and-contracts.md) authentication hardening |
| G45 | **No password reset path** (only `change-password`), no session invalidation rule on password or role change, and no admin session revocation. | Medium | Specified | [05](05-api-and-contracts.md) authentication hardening |
| G46 | **No unauthenticated health/readiness endpoints.** Only `/admin/system-health`, which a reverse proxy and container runtime cannot use. | Medium | Specified | [05](05-api-and-contracts.md) health and readiness |
| G47 | **Cancellation contract unstated** - the response is necessarily an acknowledgement, and the fate of partial outputs is undefined. | Medium | Specified | [05](05-api-and-contracts.md) cancellation semantics |
| G48 | **Workers hold database credentials and depend on the schema**, which is a legitimate choice never recorded as one. Consequence: API and worker must deploy as a matched pair, and moving workers outside the database trust boundary later is a hard change. | Medium | Specified | [05](05-api-and-contracts.md) worker-facing API |
| G49 | **No contract governance.** OpenAPI is named the source of truth with no committed artefact, no breaking-change definition, and no CI gate - so the CLI, notebook client, and MCP server rot exactly as the legacy docs did. | High | Specified | [05](05-api-and-contracts.md) contract governance, [12](12-testing-ci-and-release.md) CI pipeline |
| G50 | **Event stream operational detail missing**: SSE authentication, per-user connection limits, `Last-Event-ID` replay, proxy keep-alive, and a log-rate cap before `task.log_appended` floods a client. | Medium | Specified | [05](05-api-and-contracts.md) event stream details |

---

## F. Execution and operations gaps

| ID | Gap | Severity | Status | Addressed in |
| --- | --- | --- | --- | --- |
| G51 | **Lease protocol unspecified** - TTL sizing, heartbeat interval, requeue owner, poison-task limit, and orphaned-container reconciliation on reclaim. The most common source of stuck work. | Blocker | Specified | [06](06-execution-and-operations.md) task leases |
| G52 | **Cancellation mechanism unspecified** - the task execution step list does not mention it at all: no polling or `NOTIFY`, no SIGTERM grace period, no convergence when the owning worker is gone. | High | Specified | [06](06-execution-and-operations.md) cancellation |
| G53 | **No orphan and drift reconciliation** on worker start or periodically, so container state and task rows diverge undetected. | High | Specified | [06](06-execution-and-operations.md) orphan reconciliation |
| G54 | **Scheduler leadership is an assertion, not a mechanism.** "Exactly one active leader" with no advisory lock and no alternative. | High | Specified | [06](06-execution-and-operations.md) scheduler leadership |
| G55 | **No DST or timezone resolution rule** for schedules, although RRULE in a local zone has ambiguous and non-existent times twice a year. | Medium | Closed | ADR [0015](docs/adr/0015-recurrence-model-and-admin-recurring-jobs.md): a rule per schedule — `skip_nonexistent`, `shift_forward`, `utc_only` — with an ambiguous hour always read as its first occurrence. Implemented in `app/domain/recurrence.py`, tested against real transitions |
| G56 | **Upgrades conflict with long-running tasks.** No worker draining, no maximum drain time, no statement of whether a task killed by an upgrade is retried, and no rule permitting a migration while tasks are in flight. | High | Specified | [06](06-execution-and-operations.md) deployment interaction, [12](12-testing-ci-and-release.md) expand/contract |
| G57 | **No distributed tracing.** Four processes and a database queue; correlating a slow submit without traces is guesswork. | Medium | Specified | [06](06-execution-and-operations.md) observability |
| G58 | **No log retention or content policy**, so input values that may be sensitive can end up in logs indefinitely. | Medium | Specified | [06](06-execution-and-operations.md) observability |
| G59 | **Metrics without alert thresholds.** Oldest queued task age is this architecture's single most useful alert and is not mentioned. | Medium | Specified | [06](06-execution-and-operations.md) observability |
| G60 | **Backup has no pass condition** (no RPO/RTO), no PITR decision, no encryption or key custody, no database-versus-artifact reconciliation, no backup monitoring, and one restore test rather than a rehearsal schedule. | High | Specified | [06](06-execution-and-operations.md) backup additions, [11](11-non-functional-requirements.md) service levels |
| G61 | **Container hardening incomplete** - no statement on privileged containers, mounted container sockets, read-only root filesystem, dropped capabilities, `no-new-privileges`, or a test that no platform secret is visible inside a task. | High | Specified | [06](06-execution-and-operations.md) security additions |
| G62 | **Uploaded archive handling unspecified** - absolute paths, `..` components, and outward symlinks in a supplied archive. | High | Specified | [06](06-execution-and-operations.md) security additions |
| G63 | **Shared storage is accessed as a service account**, bypassing the POSIX permissions of institutional storage. An authorization bypass in design, presented as an implementation detail. | Blocker | Decided — [ADR 0013](docs/adr/0013-shared-storage-authorization-boundary.md), Option C: a root is exposed only within the project whose members already share it, and a `service_account` root without an attestation violates a CHECK constraint | [13](13-open-questions.md) Q13, [11](11-non-functional-requirements.md) shared-storage boundary |

---

## G. Non-functional and governance gaps

| ID | Gap | Severity | Status | Addressed in |
| --- | --- | --- | --- | --- |
| G64 | **No load or data-size numbers anywhere.** Postgres-as-queue, HTTP upload, single-VM deployment, zip packaging, and TTL retention are each only defensible inside a range that is never stated. Bioinformatics inputs plausibly reach hundreds of gigabytes. | Blocker | Specified | [11](11-non-functional-requirements.md) scale and load, [13](13-open-questions.md) Q6 |
| G65 | **No service levels** - availability, maintenance window, queue latency, RPO, RTO. Document 06's restore test therefore has no pass condition. | High | Specified | [11](11-non-functional-requirements.md) service levels |
| G66 | **No data classification or governance position**, despite a bioinformatics platform likely holding human-derived data: no encryption-at-rest decision, read auditing, verifiable deletion, ethics or DPIA gate, residency rule, or egress position. The egress question directly decides G01, because sending workflow content to a third-party LLM is a data-egress event. | Blocker | Decision needed | [11](11-non-functional-requirements.md) data governance, [13](13-open-questions.md) Q1 |
| G67 | **Retention obligations unconsidered** - funder requirements to keep outputs for years can conflict with TTL cleanup. | Medium | Specified | [11](11-non-functional-requirements.md) data governance |
| G68 | **Environment constraints unrecorded**: outbound internet availability (which decides whether images can be built on the box), Docker versus mandatory rootless Podman, institutional SSO timing, available secret manager and observability stack, and the VM specification. | High | Decision needed | [11](11-non-functional-requirements.md) environment constraints, [13](13-open-questions.md) Q7-Q8 |
| G69 | **"Later SSO" is not a plan** if the institution requires it at launch. | High | Decision needed | [13](13-open-questions.md) Q7 |

---

## H. Process gaps

| ID | Gap | Severity | Status | Addressed in |
| --- | --- | --- | --- | --- |
| G70 | **No test strategy.** Document 01 credits the current project with meaningful coverage; the plan has scattered acceptance criteria and no layered strategy, no Postgres-only rule, no per-route authorization matrix, no compiler rejection suite, no concurrency or crash-recovery tests. | High | Specified | [12](12-testing-ci-and-release.md) test strategy |
| G71 | **No CI pipeline**, so the plan's core mechanisms - generated client, committed OpenAPI, migrations matching models, examples validating - have nothing enforcing them. | High | Specified | [12](12-testing-ci-and-release.md) CI pipeline |
| G72 | **No staging environment**, so the legacy import and the upgrade path would first be rehearsed in production - which makes the Phase 9 parallel run largely meaningless. | High | Specified | [12](12-testing-ci-and-release.md) environments |
| G73 | **No expand/contract or migration-safety policy.** Without it, "rollback release" in document 06 is not actually possible once a migration has run, and index or `NOT NULL` migrations will lock the largest tables. | High | Specified | [12](12-testing-ci-and-release.md) release engineering |
| G74 | **No versioning, changelog, or branching statement**, and no "operator actions required" section per release - new environment variables, migrations, and image rebuilds are what break an upgrade. | Medium | Specified | [12](12-testing-ci-and-release.md) release engineering |
| G75 | **Developer platform parity unaddressed.** The current project is developed on Windows and PowerShell; the target runtime is rootless Podman on Red Hat with SELinux labels. Unresolved, "works on my machine" failures get blamed on the architecture. | Medium | Decision needed | [12](12-testing-ci-and-release.md) developer platform parity |
| G76 | **No seed or demo data deliverable**, although every phase's acceptance criteria assume one. | Medium | Specified | [12](12-testing-ci-and-release.md) seed and demo data |
| G77 | **Accessibility absent from the frontend plan.** Usually an institutional procurement requirement, and expensive to retrofit onto a data-table and form system. | Medium | Specified | [07](07-frontend-architecture.md) accessibility |

---

## I. Roadmap gaps

| ID | Gap | Severity | Status | Addressed in |
| --- | --- | --- | --- | --- |
| G78 | **The riskiest assumptions are proven last.** The frontend arrives at Phase 6 and legacy import at Phase 8, so whether real scientific workloads run in containers, and whether legacy published jobs can be expressed in the new format at all, are tested after the schema, compiler, and API are built around assumptions. | Blocker | Specified | [09](09-migration-roadmap.md) resequencing, Phase 0b spike |
| G79 | **Missing importers**: recurring schedules (the hardest one, G17), recurring admin jobs, template galleries, package install audit as run provenance, shared-root configuration, and the legacy directories `Jobs_Pipelines_backup/`, `outputs/`, `data/sample/`, `.bio_pipeline/job_defs_archive/`. | High | Specified | [09](09-migration-roadmap.md) missing importers |
| G80 | **Importers have no requirements** - no dry-run, no idempotency, no machine-readable report, no stated order dependencies, no reconciliation counts, and an unbounded manual-review budget behind "flag complex legacy bindings for manual migration". | High | Specified | [09](09-migration-roadmap.md) importer requirements |
| G81 | **No abort criteria.** A risk register with no exit: no conditions under which the migration stops or re-scopes, no decision owner, and no definition of what "stop" means for work already done. | High | Specified | [09](09-migration-roadmap.md) abort criteria |
| G82 | **No effort, ownership, calendar, or critical path**, and no pre-agreed cut list. A ten-phase roadmap with none of these cannot be used to plan or to say no - and the scope described plainly exceeds one part-time developer. | High | Decision needed | [09](09-migration-roadmap.md) effort and ownership |
| G83 | **Parallel-run period undefined** - no duration, no cutover decision owner, and "a defined retention period" for the read-only old system is not defined. | High | Decision needed | [09](09-migration-roadmap.md), [13](13-open-questions.md) Q17 |
| G84 | **The representative workflow set is unnamed**, so the acceptance criteria for the entire migration are undefined. | Blocker | Decision needed | [13](13-open-questions.md) Q16 |
| G85 | **Historical run migration undecided** - who needs which runs, for how long, and where the archive lives. | Medium | Decision needed | [13](13-open-questions.md) Q18 |
| G86 | **Password hash portability undecided**, which determines whether the user importer works at all and what the user communications say. | Medium | Decision needed | [13](13-open-questions.md) Q19 |
| G87 | **No training or communications plan.** "Train admins" has no owner and no materials, and the compatibility term mapping ("Published Jobs" to `Publication`) has no user-facing home. | Medium | Specified | [08](08-documentation-guidelines.md) user migration notes, [13](13-open-questions.md) Q20 |

---

## J. Documentation gaps

| ID | Gap | Severity | Status | Addressed in |
| --- | --- | --- | --- | --- |
| G88 | **Missing required documents**: task entry-point contract, expression language, configuration, non-functional requirements, data governance, disaster recovery, the cancel/stuck-run and image-promotion runbooks, the legacy import guide, user migration notes, contributing, security policy, and a changelog. | Medium | Specified | [08](08-documentation-guidelines.md) missing documents |
| G89 | **Doc metadata rules are aspirational.** `Last reviewed` and `Applies to version` are required but unchecked - which is exactly how the drift diagnosed in document 01 happened. | Medium | Specified | [08](08-documentation-guidelines.md) checkable metadata |
| G90 | **Runbooks are never executed.** A runbook nobody runs is a runbook that is wrong. | Medium | Specified | [08](08-documentation-guidelines.md) additional CI doc checks |

---

## Closure criteria

This register is closed when:

1. Every `Decision needed` row has an accepted or superseded ADR under
   [docs/adr](docs/adr/README.md) recording the answer, date, decision owner, and
   follow-up updates. A proposed ADR stub does not close the row.
2. Every `Blocker` row is resolved before the phase it blocks begins - G01, G02,
   G20, G21, G24, G51, G63, G64, G66, G78, and G84 before Phase 1 work starts.
3. Every `Specified` row has an entry in
   [14-gap-closure-ledger.md](14-gap-closure-ledger.md) with owner, tracker,
   verification method, and a v1/defer/drop disposition.
4. Every `Specified` row is either implemented or consciously moved to the
   `Defer` or `Drop` disposition in
   [10-feature-parity-and-scope.md](10-feature-parity-and-scope.md) or a
   follow-on ADR.
5. No `Open` rows remain. There are none at the time of writing; a row added
   later starts as `Open`.

## Maintenance

Add a row for each new gap found, keep the ID stable, and never renumber. Record
the resolution in the ADR, not by deleting the row - the register is also the
record of what the plan got wrong and when it was noticed.

When adding a `Decision needed` row, create a matching ADR stub and add it to
[13-open-questions.md](13-open-questions.md). When adding a `Specified` row, add
it to [14-gap-closure-ledger.md](14-gap-closure-ledger.md) before treating the
gap as tracked.
