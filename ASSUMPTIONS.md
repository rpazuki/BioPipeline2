# Implementation Assumptions

17 of 31 ADRs in [`migration/docs/adr`](migration/docs/adr/) are now
accepted. This file records only the places where the code still assumes an
answer nobody has given.

Implementation began before the decisions were complete, deliberately and
narrowly:

- Most of the Phase 1 foundation is **decision-independent**. The domain
  vocabulary, the lifecycle rules, and the bulk of the schema are the same
  whichever way the open questions resolve.
- The two hardest blockers, `G20` (task entry-point contract) and `G21`
  (expression language), are **specifications to write, not preferences to
  choose**. Writing them is how they close. Both are now implemented and
  tested, which turns two abstract blockers into two concrete proposals that
  can be accepted or amended.
- Nothing here touches the decisions that are genuinely the project owner's to
  make: whether the AI Designer or MCP server ship, what the load targets are,
  whether the data is identifiable, or when cutover happens.

This file records every place the code assumes an answer. **Each row is a
question that still needs a real decision.** When an ADR is accepted, update
the row: either the code already matches, or it needs changing.

## Assumptions taken

| ADR | Question | Assumed here | Why this default | Cost to reverse |
| --- | --- | --- | --- | --- |
| ~~0009~~ | Tenancy | `projects` table exists; every owned entity carries `project_id`; one default project is seeded | Persistence rule 8 requires the columns. Adding them later is a migration across every large table; leaving them unused costs a few bytes per row | Low if dropped, high if added later |
| ~~0011~~ | Enum representation | `text` + named CHECK, generated from `app.domain.enums` | Adding a value is an ordinary migration; Postgres cannot drop an enum label | Low |
| ~~0012~~ | Delete semantics | Soft delete (`deleted_at`), with a separate `purged_at` for when bytes are actually gone | Distinguishes "hidden from the user" from "verifiably destroyed", which is what a deletion guarantee needs | Low |
| ~~0010~~ | Configuration | `pydantic-settings`; precedence defaults → optional YAML → environment; secrets from the environment only; frontend settings served at runtime from an allowlist | Keeps the current system's profile-based YAML while making secrets and the public subset explicit | Low |
| ~~0005~~ | Task entry-point contract | Implemented as [`task_contract.py`](backend/app/domain/task_contract.py) v1.0 and [documented](docs/architecture/task-entry-point-contract.md) | Blocks the compiler and executor; had to be made concrete | Medium — task images depend on it |
| ~~0008~~ | Container runtime | **Decided:** Docker on a generic Linux VM | — | — |
| ~~0007~~ | SSO | `users.password_hash` is nullable and `auth_provider` exists, so an external provider can be added without a schema change | Costs nothing now, avoids a migration later | Low |
| 0023 | Task secrets | Tasks need **no** secrets; the spec model rejects credential-shaped environment variables | Safest default. If it is wrong, it fails loudly at the boundary rather than leaking | Medium |
| 0013 | Shared storage identity (**still blocking**) | **Not implemented.** `shared_storage_roots.identity_mode` records the choice per root and defaults to `service_account`, but no shared-storage access code exists yet | This is a security decision (`G63`, Blocker). Recording it per root beats assuming it globally, and writing the access path before the decision would bake in the bypass | n/a — nothing built on it |
| 0015 | Recurrence | Both representations supported; a CHECK requires each schedule to pick exactly one | Existing interval schedules import losslessly while RRULE is available; the decision can be made per schedule and migrated later | Low |
| ~~0001~~ | Data governance | Read auditing is **on** by default (`artifact_access_events`, `audit_artifact_reads=true`) | Relaxing later is cheap; retrofitting read auditing is not | Low |

## Deliberately not built

These are blocked on a decision, and building them would bake in an answer:

- **Shared-storage access** — blocked on ADR 0013 (`G63`).
- **AI Designer** — blocked on ADR 0002 and ADR 0001 (data egress).
- **MCP server** — blocked on ADR 0003.
- **Notifications** — blocked on ADR 0014.
- **Anything sized against load numbers** (queue tuning, packaging strategy,
  upload cutover thresholds) — blocked on ADR 0006.

## What the code does *not* assume

The schema carries no assumption about scale, retention windows, SLOs, or
whether the deployment is single-project in practice. Those stay settings and
policy rows rather than structure, so answering them later is configuration
rather than migration.

## Struck-through rows are decided

`~~0009~~` means the assumption became an accepted decision and the code
already matches it. The live state of all thirty is in
[`migration/docs/adr/README.md`](migration/docs/adr/README.md).
