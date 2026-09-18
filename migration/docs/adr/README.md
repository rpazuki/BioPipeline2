# ADR Queue

This folder contains the decision records required to close `Decision needed` rows in `../../gaps.md` and the open questions in `../../13-open-questions.md`.

A gap is not closed until its ADR is `Accepted` or `Superseded` and the affected planning documents are updated or explicitly left unchanged.

**21 of 33 are decided.** The remaining 12 are genuinely open and are listed
separately below, so an open question is not mistaken for a settled one.

## Workflow

1. Pick the ADR tied to the blocking question.
2. Fill in the options, decision, consequences, owner, and date.
3. Change `Status` to `Accepted` once the project owner agrees.
4. Update `../../gaps.md`, `../../14-gap-closure-ledger.md`, and any referenced design document if the decision changes the plan.
5. Never delete an ADR after acceptance. If a later decision changes it, create a superseding ADR and mark the old one `Superseded`.

## Decided

| ADR | Title | Decision in one line |
| --- | --- | --- |
| [0001](./0001-data-governance-and-classification.md) | Data governance and classification | The platform holds no corpus; TTL cleanup, history survives, read auditing on |
| [0005](./0005-task-entry-point-contract.md) | Task entry-point contract | JSON `task.json` / `result.json`, contract v1.0, worker verifies outputs itself |
| [0006](./0006-load-and-data-size-targets.md) | Load and data-size targets | 5-20 users, one VM, tasks from sub-second to 24 h, inputs to tens of GB |
| [0008](./0008-production-runtime-and-network.md) | Production runtime | Docker on a generic Linux VM; no Podman, SELinux or Red Hat specifics |
| [0009](./0009-tenancy-and-project-scope.md) | Tenancy | Columns present, one default project seeded, no scoping built |
| [0010](./0010-configuration-strategy.md) | Configuration | defaults -> optional YAML -> environment; secrets from environment only |
| [0011](./0011-enum-representation.md) | Enum representation | `text` plus named CHECK, generated from one Python enum |
| [0012](./0012-delete-semantics.md) | Delete semantics | TTL on bytes, run history survives, no `expired` run status |
| [0018](./0018-historical-run-migration.md) | Historical run migration | Moot: nothing is migrated |
| [0019](./0019-password-hash-portability.md) | Password hash portability | Moot: no users imported |
| [0024](./0024-developer-platform-parity.md) | Developer platform parity | Docker everywhere; the Podman divergence dissolved |
| [0026](./0026-collapse-authoring-levels.md) | Collapse authoring levels | One `Pipeline`, not pipeline plus workflow |
| [0027](./0027-authoring-format-and-references.md) | Authoring format | `{brace}` templating, explicit whole-value rule, unresolvable is an error |
| [0028](./0028-execution-mechanism-and-snapshots.md) | Execution mechanism | Container plus mounted mutable venv, per-run snapshot |
| [0029](./0029-resource-admission-control.md) | Resource admission control | Resource requests, not a serial queue |
| [0030](./0030-execution-trust-model.md) | Execution trust model | Admin code trusted; researcher input is not |
| [0013](./0013-shared-storage-authorization-boundary.md) | Shared-storage authorization | Service account, and only for roots attested as already shared |
| [0015](./0015-recurrence-model-and-admin-recurring-jobs.md) | Recurrence model | Both representations; RRULE is what the UI composes; a DST rule per schedule |
| [0031](./0031-publication-binding-plan.md) | Publication bindings | Bindings resolve at publish time against the compiled IR |
| [0032](./0032-stage-as-the-unit-of-execution.md) | Unit of execution | One container per stage-task, not per step |
| [0033](./0033-upload-transport-and-the-large-input-path.md) | Upload transport | Offset-append over HTTP for small files; the share is the path for tens of GB |

## Still open

These block the phases named in [14-gap-closure-ledger.md](../../14-gap-closure-ledger.md).

| ADR | Question | Related gaps | Blocking |
| --- | --- | --- | --- |
| [0002](./0002-ai-pipeline-designer-scope.md) | Is the AI Pipeline Designer in v1? | G01 | Scope |
| [0003](./0003-mcp-server-scope-and-contract.md) | Is the MCP server in v1? | G02 | API naming; decide before the contract freezes |
| [0004](./0004-cli-and-notebook-client-scope.md) | Which non-frontend clients survive? | G03, G04 | An admin bootstrap path is required regardless |
| [0007](./0007-sso-at-launch.md) | Is institutional SSO required at launch? | G68, G69 | Auth surface |
| [0014](./0014-notifications-scope.md) | Are notifications in scope? | G12 | Raised in priority by day-long tasks; a researcher waiting a day needs telling |
| [0016](./0016-representative-workflow-set.md) | Which pipelines must work on day one? | G84 | Acceptance criteria |
| [0017](./0017-parallel-run-and-cutover-window.md) | Cutover window and owner | G83 | Reduced in scope: no parallel data running, but the old system's retirement still needs a date |
| [0020](./0020-training-and-user-communications.md) | Training and comms | G87 | Cutover |
| [0021](./0021-in-app-backup-restore-scope.md) | Is in-app backup a feature? | G08 | Scope |
| [0022](./0022-ad-hoc-admin-submission-scope.md) | Does ad-hoc admin submission survive? | G09 | Scope |
| [0023](./0023-task-secret-model.md) | Do tasks need secrets? | G35 | The task contract currently assumes not, and enforces it |
| [0025](./0025-effort-ownership-calendar-and-cut-list.md) | Effort, ownership, cut list | G82 | Planning |
