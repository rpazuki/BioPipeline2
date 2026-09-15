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

## Answered

Sixteen of the original questions are decided; each has an accepted ADR in
[docs/adr](docs/adr/README.md).

| Q | Answer |
| --- | --- |
| Q1 | The platform holds no data corpus. Non-identifiable, TTL cleanup, history survives. ADR 0001 |
| Q5 | Task entry-point contract defined and implemented. ADR 0005 |
| Q6 | 5-20 users, one VM, tasks from sub-second to 24 h, inputs to tens of GB. ADR 0006 |
| Q8 | Docker on a generic Linux VM. ADR 0008 |
| Q9 | Single project; columns present, no scoping built. ADR 0009 |
| Q10 | defaults -> optional YAML -> environment; secrets from environment only. ADR 0010 |
| Q11 | `text` plus named CHECK, from one Python enum. ADR 0011 |
| Q12 | TTL on bytes, run history survives, no `expired` run status. ADR 0012 |
| Q18 | Moot: nothing is migrated. ADR 0018 |
| Q19 | Moot: no users imported. ADR 0019 |
| Q24 | Docker everywhere; the Podman divergence dissolved. ADR 0024 |
| new | One `Pipeline`, not pipeline plus workflow. ADR 0026 |
| new | `{brace}` templating with an explicit whole-value rule. ADR 0027 |
| new | Container plus mounted mutable venv, per-run snapshot. ADR 0028 |
| new | Resource admission control, not a serial queue. ADR 0029 |
| new | Admin code trusted; researcher input is not. ADR 0030 |
| Q13 | Service account, with a root exposed only when every user reaching it already has equivalent access. Attestation enforced by constraint. ADR 0013 |

## Still blocking

| # | Question | Why it blocks | ADR |
| --- | --- | --- | --- |
| Q16 | Which pipelines must work on day one? | It is the acceptance criterion for the whole project. Likely `growth_rate_fit_pipeline`, `amn_pipeline`, `collateing_pipeline`, and the FBA set. | [0016](docs/adr/0016-representative-workflow-set.md) |
| Q2 | Is the AI Pipeline Designer in v1? | An entire bounded context, and a data-egress decision. Recommended: defer to v2. | [0002](docs/adr/0002-ai-pipeline-designer-scope.md) |
| Q3 | Is the MCP server in v1? | 74 tools map 1:1 to route names. Decide before the API contract freezes, or it is a second rewrite. | [0003](docs/adr/0003-mcp-server-scope-and-contract.md) |
| Q4 | Which non-frontend clients survive? | An admin bootstrap path is required regardless: something must create the first user. | [0004](docs/adr/0004-cli-and-notebook-client-scope.md) |
| Q7 | Is institutional SSO required at launch? | The schema supports it without change, so this is a scope question rather than a design one. | [0007](docs/adr/0007-sso-at-launch.md) |
| Q14 | Are notifications in scope? | Priority raised: a day-long task with no completion notice is a real usability failure. Recommended for v1. | [0014](docs/adr/0014-notifications-scope.md) |
| Q15 | RRULE or interval recurrence? | Both are in the schema. There are 0 schedules in the real deployment, so this only decides what the UI offers. | [0015](docs/adr/0015-recurrence-model-and-admin-recurring-jobs.md) |
| Q23 | Do tasks need secrets? | The task contract assumes not and enforces it by rejecting credential-shaped environment variables. If a pipeline must reach an external service, that changes. | [0023](docs/adr/0023-task-secret-model.md) |
| Q17, Q20 | Retirement date for the old deployment, and who trains whom | Reduced in scope: no data moves, but the old system still needs a stated end date. | [0017](docs/adr/0017-parallel-run-and-cutover-window.md), [0020](docs/adr/0020-training-and-user-communications.md) |
| Q21, Q22 | Does in-app backup survive? Does ad-hoc admin submission survive? | Scope. Both are small. | [0021](docs/adr/0021-in-app-backup-restore-scope.md), [0022](docs/adr/0022-ad-hoc-admin-submission-scope.md) |
| Q25 | Effort, ownership, calendar, cut list | The plan still has no time dimension and no agreed cut list. | [0025](docs/adr/0025-effort-ownership-calendar-and-cut-list.md) |

## Decision log

Each answer is an ADR under [docs/adr](docs/adr/README.md), dated, with the
options considered. This folder describes intent; the ADRs record what was
decided and why.
