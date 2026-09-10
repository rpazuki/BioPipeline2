# Open Questions and Required Decisions

Documents 01-09 read as a finished plan, but several of their choices depend on
answers that are not recorded anywhere. This is the decision queue. Each item
says who is blocked by it and when it must be answered.

Answer the `Blocking Phase 0/1` items before writing code. Nothing below is
rhetorical; each one changes the design if answered a different way.

These are the `Decision needed` rows of [gaps.md](gaps.md), restated as questions
with defaults. Every answer becomes an ADR; that is how a row closes.
Question IDs are stable. Later additions may appear in a phase table out of
numeric order; do not renumber older questions.

## Blocking Phase 0

| # | Question | Why it blocks | Default if unanswered |
| --- | --- | --- | --- |
| 1 | Will the platform hold human-derived or otherwise identifiable data? | Governs encryption, read auditing, deletion guarantees, whether the AI Designer may call an external API at all, and whether ethics approval is a prerequisite. See [11-non-functional-requirements.md](11-non-functional-requirements.md). | Assume yes and design for it; relaxing later is cheap, retrofitting is not. |
| 2 | Is the AI Pipeline Designer in scope for v1? | An entire bounded context, data model, UI surface, secret-handling story, and egress review. Absent from 01-09. | Defer to v2, and say so in the release notes. |
| 3 | Is the MCP server in scope for v1? | ~71 tools map 1:1 to `/api/v1` routes. The rename from `published-jobs` to `publications` breaks all of them. Deciding late means either a frozen legacy API shape or a second rewrite. | Carry, but as a generated or contract-tested consumer, not a hand-maintained mirror. |
| 4 | Do the CLI and the notebook client survive? | They are the reason the legacy architecture pushed logic into a shared layer. At minimum an admin bootstrap CLI is required to create the first user. | Ship an admin CLI in v1; defer the researcher notebook client. |
| 5 | How does a workflow reference an external science function under container execution? | Blocks the Phase 2 compiler and the Phase 3 execution adapter. Today YAML names `labUtils.*` callables imported in-process. In a container that needs an entry-point contract, argument marshalling, and an output convention. | Define a task entry-point contract in Phase 1, before the compiler. |
| 6 | What are the load and data-size numbers? | Postgres-as-queue, HTTP upload, zip packaging, and single-VM deployment are all only valid inside a range. | Do not defer. Rough numbers beat none. |
| 7 | Is institutional SSO required at launch? | "Later SSO" in document 05 is a plan only if the answer is no. | Design the session contract so an OIDC provider can be added without changing the frontend. |
| 8 | Docker or rootless Podman in production, and is outbound internet available? | Determines whether task images can be built on the box, whether a mirror is needed, and the SELinux mount handling. | Rootless Podman, no outbound access, internal registry required. |
| 24 | What developer platforms are supported during implementation? | The current project has Windows/PowerShell development history, while production targets Red Hat, rootless Podman, and SELinux. If parity is not designed, environment failures will look like architecture failures. | Support macOS/Linux directly; provide documented containerized or remote development for Windows; test Podman/SELinux behavior in CI or staging. |
| 25 | Who owns effort, calendar, critical path, and the cut/defer list? | The plan is too broad for implicit ownership. Without named owners and a cut list, scope will expand until the migration stalls. | Assign a project owner and technical owner before Phase 0 ends; maintain a pre-agreed v1 cut/defer list. |

## Blocking Phase 1

| # | Question | Why it blocks |
| --- | --- | --- |
| 9 | Multi-project or single-project? Persistence rule 8 in document 04 requires tenant/project columns, but no `projects` table, no project scoping in the API, and no project-level RBAC exists in the plan. | Half-applied tenancy is worse than either choice. Decide, then either add the table and scope every query, or drop the rule. |
| 10 | Config strategy: keep a unified `app_config.yaml` with environment profiles as today, or move to environment variables plus `settings.py`? Which values are exposed to the frontend, and where do secrets live? | Affects deployment, the frontend build, and the secret-handling story. |
| 11 | Enum representation: native Postgres enums, `text` plus check constraints, or a lookup table? Document 04 currently mixes the first two. | Adding a value to a native enum is a migration; a check constraint is easier to evolve. Pick one and apply it everywhere. |
| 12 | Soft delete or hard delete for runs and artifacts? `DELETE /runs/{id}`, an `expired` status, and `deleted_at` columns coexist in the plan with no stated semantics. | Determines the audit story and the "verifiable deletion" answer to question 1. |
| 13 | Does the platform act as the requesting user against shared storage, or as a single service account? | The current design writes as the service account, which bypasses the POSIX permissions of institutional storage. This is a security decision, not an implementation detail. |
| 14 | Are notifications in scope? Document 02 lists an email adapter; nothing else in the plan uses it. | Long runs with no completion notice is a real usability problem. Specify it or remove the adapter. |
| 15 | Recurrence model: RRULE as proposed, or the existing "every N units" interval? Do recurring admin jobs survive separately from researcher schedules? | RRULE is more capable but requires a migration mapping for existing schedules and a DST policy. Admin recurring jobs are a separate legacy concept and cannot disappear by accident. |
| 21 | Is in-app backup/restore a v1 application feature, an operator-only runbook, or both? | The old system has an in-app backup page. With Postgres plus artifact volumes, backup semantics are broader and riskier than downloading one bundle. |
| 22 | Does ad-hoc admin direct-run survive? | The old submit page and one-off queue path let admins run work outside the published catalog. The new model should either expose direct runs of workflow revisions or deliberately drop the capability. |
| 23 | Can tasks receive secrets? If yes, where do secrets live and how are they injected? | External-service credentials cannot be improvised later. This affects the data model, execution adapter, audit policy, and container hardening. |

## Blocking Phase 8 and 9

| # | Question | Why it blocks |
| --- | --- | --- |
| 16 | Which specific workflows, publications, and users must work on day one? Document 09 says "a small set of representative workflows" without naming them. | The acceptance criteria for the whole migration are undefined until this list exists. |
| 17 | How long does the parallel-run period last, and who decides cutover? | Document 09 has no duration, no owner, and no abort criteria. |
| 18 | What happens to historical runs? Document 09 prefers a read-only archive but does not say who needs which runs, for how long, or where the archive lives. | Determines the importer scope and the storage budget. |
| 19 | Do existing password hashes transfer, or is a forced reset acceptable? | Determines whether the user importer is viable and what the user comms say. |
| 20 | Who trains admins and researchers, and what artefacts do they get? Document 09 says "train admins" with no owner or material. | Cutover risk. |

## Decision log

Record each answer as a dated ADR under [docs/adr](docs/adr/README.md), not as
an edit to these documents. The plan folder describes intent; the ADRs record
what was decided and why. Proposed ADR stubs now exist for every current
question; they do not close a question until the ADR status is changed to
`Accepted` or `Superseded`.

## ADR queue

| Question | ADR | Related gaps |
| --- | --- | --- |
| Q1 | [ADR 0001: Data governance and data classification](docs/adr/0001-data-governance-and-classification.md) | G66, G01 |
| Q2 | [ADR 0002: AI Pipeline Designer scope](docs/adr/0002-ai-pipeline-designer-scope.md) | G01 |
| Q3 | [ADR 0003: MCP server scope and contract](docs/adr/0003-mcp-server-scope-and-contract.md) | G02 |
| Q4 | [ADR 0004: CLI and notebook client scope](docs/adr/0004-cli-and-notebook-client-scope.md) | G03, G04 |
| Q5 | [ADR 0005: Task entry-point contract](docs/adr/0005-task-entry-point-contract.md) | G20 |
| Q6 | [ADR 0006: Load and data-size targets](docs/adr/0006-load-and-data-size-targets.md) | G64 |
| Q7 | [ADR 0007: SSO requirement at launch](docs/adr/0007-sso-at-launch.md) | G68, G69 |
| Q8 | [ADR 0008: Production container runtime and network constraints](docs/adr/0008-production-runtime-and-network.md) | G68 |
| Q9 | [ADR 0009: Tenancy and project scope](docs/adr/0009-tenancy-and-project-scope.md) | G29 |
| Q10 | [ADR 0010: Configuration strategy](docs/adr/0010-configuration-strategy.md) | G11 |
| Q11 | [ADR 0011: Enum representation](docs/adr/0011-enum-representation.md) | G37 |
| Q12 | [ADR 0012: Delete semantics for runs and artifacts](docs/adr/0012-delete-semantics.md) | G36 |
| Q13 | [ADR 0013: Shared storage authorization boundary](docs/adr/0013-shared-storage-authorization-boundary.md) | G63 |
| Q14 | [ADR 0014: Notifications scope](docs/adr/0014-notifications-scope.md) | G12 |
| Q15 | [ADR 0015: Recurrence model and admin recurring jobs](docs/adr/0015-recurrence-model-and-admin-recurring-jobs.md) | G10, G17 |
| Q16 | [ADR 0016: Representative workflow set for acceptance](docs/adr/0016-representative-workflow-set.md) | G84 |
| Q17 | [ADR 0017: Parallel-run and cutover window](docs/adr/0017-parallel-run-and-cutover-window.md) | G83 |
| Q18 | [ADR 0018: Historical run migration and archive policy](docs/adr/0018-historical-run-migration.md) | G85 |
| Q19 | [ADR 0019: Password hash portability and reset policy](docs/adr/0019-password-hash-portability.md) | G86 |
| Q20 | [ADR 0020: Training and user communications](docs/adr/0020-training-and-user-communications.md) | G87 |
| Q21 | [ADR 0021: In-app backup and restore scope](docs/adr/0021-in-app-backup-restore-scope.md) | G08 |
| Q22 | [ADR 0022: Ad-hoc admin submission scope](docs/adr/0022-ad-hoc-admin-submission-scope.md) | G09 |
| Q23 | [ADR 0023: Task secret model](docs/adr/0023-task-secret-model.md) | G35 |
| Q24 | [ADR 0024: Developer platform parity](docs/adr/0024-developer-platform-parity.md) | G75 |
| Q25 | [ADR 0025: Effort, ownership, calendar, and cut list](docs/adr/0025-effort-ownership-calendar-and-cut-list.md) | G82 |
