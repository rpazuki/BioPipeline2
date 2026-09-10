# ADR Queue

This folder contains the decision records required to close `Decision needed` rows in `../../gaps.md` and the open questions in `../../13-open-questions.md`.

All files are created as `Status: Proposed`. A gap is not closed until its ADR is updated to `Accepted` or `Superseded` and the affected planning documents are updated or explicitly left unchanged.

## Workflow

1. Pick the ADR tied to the blocking question.
2. Fill in the options, decision, consequences, owner, and date.
3. Change `Status` to `Accepted` once the project owner agrees.
4. Update `../../gaps.md`, `../../14-gap-closure-ledger.md`, and any referenced design document if the decision changes the plan.
5. Never delete an ADR after acceptance. If a later decision changes it, create a superseding ADR and mark the old one `Superseded`.

## Current queue

| ADR | Question | Related gaps | Title |
| --- | --- | --- | --- |
| [0001](./0001-data-governance-and-classification.md) | Q1 | G66, G01 | Data governance and data classification |
| [0002](./0002-ai-pipeline-designer-scope.md) | Q2 | G01 | AI Pipeline Designer scope |
| [0003](./0003-mcp-server-scope-and-contract.md) | Q3 | G02 | MCP server scope and contract |
| [0004](./0004-cli-and-notebook-client-scope.md) | Q4 | G03, G04 | CLI and notebook client scope |
| [0005](./0005-task-entry-point-contract.md) | Q5 | G20 | Task entry-point contract |
| [0006](./0006-load-and-data-size-targets.md) | Q6 | G64 | Load and data-size targets |
| [0007](./0007-sso-at-launch.md) | Q7 | G68, G69 | SSO requirement at launch |
| [0008](./0008-production-runtime-and-network.md) | Q8 | G68 | Production container runtime and network constraints |
| [0009](./0009-tenancy-and-project-scope.md) | Q9 | G29 | Tenancy and project scope |
| [0010](./0010-configuration-strategy.md) | Q10 | G11 | Configuration strategy |
| [0011](./0011-enum-representation.md) | Q11 | G37 | Enum representation |
| [0012](./0012-delete-semantics.md) | Q12 | G36 | Delete semantics for runs and artifacts |
| [0013](./0013-shared-storage-authorization-boundary.md) | Q13 | G63 | Shared storage authorization boundary |
| [0014](./0014-notifications-scope.md) | Q14 | G12 | Notifications scope |
| [0015](./0015-recurrence-model-and-admin-recurring-jobs.md) | Q15 | G10, G17 | Recurrence model and admin recurring jobs |
| [0016](./0016-representative-workflow-set.md) | Q16 | G84 | Representative workflow set for acceptance |
| [0017](./0017-parallel-run-and-cutover-window.md) | Q17 | G83 | Parallel-run and cutover window |
| [0018](./0018-historical-run-migration.md) | Q18 | G85 | Historical run migration and archive policy |
| [0019](./0019-password-hash-portability.md) | Q19 | G86 | Password hash portability and reset policy |
| [0020](./0020-training-and-user-communications.md) | Q20 | G87 | Training and user communications |
| [0021](./0021-in-app-backup-restore-scope.md) | Q21 | G08 | In-app backup and restore scope |
| [0022](./0022-ad-hoc-admin-submission-scope.md) | Q22 | G09 | Ad-hoc admin submission scope |
| [0023](./0023-task-secret-model.md) | Q23 | G35 | Task secret model |
| [0024](./0024-developer-platform-parity.md) | Q24 | G75 | Developer platform parity |
| [0025](./0025-effort-ownership-calendar-and-cut-list.md) | Q25 | G82 | Effort, ownership, calendar, and cut list |
