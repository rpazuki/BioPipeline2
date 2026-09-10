# Feature Parity and Scope Decisions

Documents 01-09 describe the target system well, but they never enumerate the
existing feature surface and say, for each item, whether BioPipeline2 keeps it,
replaces it, defers it, or drops it. Several whole subsystems in the current
repository are not mentioned anywhere in the plan. That is a scope risk: work
that is invisible in the roadmap is work that is not estimated, not staffed, and
not accepted.

This document is the parity ledger. Every row must have an owner and a decision
before Phase 1 closes. `Undecided` rows are tracked in
[13-open-questions.md](13-open-questions.md), and the gaps that produced this
ledger are rows G01-G13 and G14-G19 of [gaps.md](gaps.md).

## Legend

- **Carry**: rebuild in BioPipeline2 with the new domain model.
- **Replace**: capability survives, mechanism changes.
- **Defer**: not in v1, explicitly planned for a later release.
- **Drop**: intentionally removed; users must be told.
- **Undecided**: needs a decision from the project owner.

## Parity ledger

| # | Current capability | Where it lives today | Covered by docs 01-09? | Decision | Notes |
| --- | --- | --- | --- | --- | --- |
| 1 | Pipeline YAML store, validation, templates gallery | `yaml_store.py`, `yaml_validation.py`, `templates.py`, routes `/pipeline-yamls`, `/validation`, `/templates` | Partly - templates gallery is absent | Carry | Template gallery must appear in the pipeline/workflow authoring UX and API. |
| 2 | Job Definitions incl. templates | `job_definition*.py`, `/job-definitions`, `/job-definition-templates` | Partly - templates absent | Replace | Becomes WorkflowTemplate + WorkflowRevision; keep a starter-template catalog. |
| 3 | One-off task queue and submit page | `job_queue.py`, `runner.py`, `worker.py`, `/jobs`, `submit/` | Not mentioned | Undecided | Admin ad-hoc submission is not in the new model. Either expose "run a workflow revision directly" or drop the page and say so. |
| 4 | Published jobs, catalog, my-runs, my-schedules | `published_jobs.py`, `published_runs.py` | Yes | Carry | Core of the redesign. |
| 5 | Run workspaces, containment, artifact.zip packaging | `run_workspace.py`, `run_reaper.py` | Yes | Carry | |
| 6 | **Output delivery to shared storage** | `run_reaper.py` copies fields with `delivery: ["shared"]` into an allowlisted shared root | **No** | Carry | Docs 03/04/05 model input `source_policy` but no output `delivery_policy`. See patches in 03/04/05/06. |
| 7 | **`url` input source (server-side fetch)** | `published_jobs.py` `_fetch_url`, `urlopen(..., timeout=30)` | **No** | Carry with hardening | Plan lists only `upload` and `shared`. Server-side fetch is an SSRF surface and needs an allowlist, scheme restriction, size cap, redirect policy. |
| 8 | **Chunked / resumable uploads** | `published_jobs.py` offset-append streaming upload | **No** | Carry | Plan's single `POST /files/uploads` is a regression for multi-GB genomics inputs. |
| 9 | Workspace byte quota | `run_workspace.py` `max_bytes` | Column exists (`workspaces.quota_bytes`) | Carry | Add per-user and global quota, not just per-run. |
| 10 | Typed value library, saved values, Python type import | `type_*.py`, `typed_value_store.py` | Yes | Carry | |
| 11 | Recurring schedules (researcher) and recurring admin jobs | `recurring_schedule.py`, `recurring_job.py` | Partly | Replace | Legacy is interval-based ("every N units"); plan proposes RRULE. Needs a mapping and an importer (missing from Phase 8). Admin recurring jobs have no successor - decide. |
| 12 | **Package install / uninstall from the Environment page**, with an install audit DB | `packages.py`, `package_introspect.py`, `installs.sqlite`, `/packages` | **No** - replaced silently | Replace | Immutable `runtime_environments` images remove live installs. That is the right call, but it deletes an admin capability. Needs a replacement workflow: image definition, build, promote, roll back, plus read-only introspection of what is inside an image. |
| 13 | Package introspection (list/search installed functions and classes, get a signature) | `package_introspect.py`, `/packages/inspect|search|signature` | **No** | Carry | The authoring UX depends on it - it is how an admin discovers callable science functions. |
| 14 | **In-app backup / restore** | `backup.py`, `/backup`, `backup/` page | Only as an ops runbook and one endpoint | Undecided | With Postgres plus an artifact volume, an in-app "download a backup" button has different semantics. Decide: app feature, ops-only, or both. |
| 15 | Auth: username/password, opaque server sessions, sliding renewal, two roles | `auth_*.py` | Yes | Carry | Add CSRF, login rate limiting, lockout, password policy - see 05 patch. |
| 16 | **AI Pipeline Designer (admin chat)** | `ai_agent.py`, `ai_providers.py`, `ai_tools.py`, `ai_schema_provider.py`, `/ai-chat`, `ai-chat/` page, provider config in `app_config.yaml` | **No** | Undecided | A whole subsystem with multi-provider config, a tool loop, iteration and wall-clock budgets, and secret handling. If it is carried, it needs a bounded context, tables (conversations, messages, tool calls), an API, a UI, and a cost/abuse policy. If it is dropped, say so in the release notes. |
| 17 | **MCP server, ~71 tools, stdio + streamable HTTP** | `mcp/`, separate package and venv, bearer-token HTTP transport for Cowork / claude.ai | **No** | Undecided | Every tool maps to a `/api/v1` route. Renaming `published-jobs` to `publications` breaks all of them. Decide whether the MCP server is a v1 deliverable, and if so make it a first-class contract consumer so OpenAPI changes fail its build. |
| 18 | **CLI (`bio-pipeline`)** | `cli.py`, entry point `cli:main` | **No** | Undecided | Legacy architecture principle was "HTTP API and CLI stay thin, logic in the shared layer". The new layering supports it, but no doc names a CLI deliverable. Operators use it for bootstrap (`auth bootstrap-admin`) - at minimum an admin bootstrap path is required. |
| 19 | **Python / notebook client** | `client.py`, plus the legacy standalone `create_app` | **No** | Undecided | Researchers driving runs from notebooks is a plausible requirement. If kept, it should be generated or thin over the same OpenAPI. |
| 20 | Multi-app gateway / path-prefix deployment knowledge | `docs/multi-app-gateway-solution.md`, `docs/multi-path-app-porting-guide.md`, `configs/app_config.yaml` `base_path` | Path prefix is required in 06/07 | Carry | Reuse the existing gateway findings rather than rediscovering them. |
| 21 | Unified `configs/app_config.yaml` with environment profiles shared by frontend and backend | `configs/` | **No** - plan only says `.env` plus `settings.py` | Undecided | Decide the config strategy: precedence, validation at boot, which values are public to the frontend, where secrets live. |
| 22 | External science packages imported by name from YAML (`labUtils.*`) | `src/pipeline/engine.py` | Stated as a principle to keep, mechanism unspecified | **Gap** | Under container execution, how does a workflow reference a Python callable? Entry-point contract, argument marshalling, and result/output convention are undefined. This blocks Phase 2 and Phase 3. |
| 23 | Notifications / email | Not implemented today | 02 lists an "email" infrastructure adapter | Undecided | Long runs finishing with no notification is a real usability gap. Either specify it (tables, templates, opt-out) or remove the adapter from 02. |

## Explicit non-goals

Record what BioPipeline2 v1 will **not** do, so scope creep is visible:

- No cross-institution multi-tenancy (but keep the project column - see 04).
- No Kubernetes or OpenShift deployment in v1.
- No distributed multi-node workers in v1.
- No cost accounting or billing.
- Anything marked `Defer` or `Drop` above.

## Rule

No feature may be built in BioPipeline2 that is not either (a) a row in this
ledger with a `Carry`/`Replace` decision, or (b) a new requirement added to this
ledger with a dated entry. This keeps the rebuild from re-growing the accidental
surface that document 01 diagnoses.
