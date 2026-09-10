# Non-Functional Requirements

Documents 01-09 contain no numbers. Every significant technical choice in them -
Postgres as the queue, a single VM, HTTP uploads, TTL retention, one worker
container per task - is only defensible against a stated load. Without targets
there is no way to accept the system or to know when to add Redis, more workers,
or object storage.

Fill in the `Target` column before Phase 1 closes. The `Why it matters` column
says which decision the number governs.

Registered as rows G64-G69 (and G18, G34, G63) of [gaps.md](gaps.md). G64 and
G66 are blockers.

## Scale and load

| Dimension | Target | Why it matters |
| --- | --- | --- |
| Named users total | TBD | Session store sizing, user admin UX. |
| Concurrent active users | TBD | API replica count, connection pool size. |
| Runs per day (peak) | TBD | Scheduler and worker throughput; whether Postgres queueing suffices. |
| Tasks per run (median / p95 / max) | TBD | Fan-out limits, task table growth, run detail page paging. |
| Task wall-clock duration (median / p95 / max) | TBD | Lease TTL, heartbeat interval, timeout defaults, cancellation grace period. |
| Concurrent running tasks per host | TBD | CPU/memory reservation, container resource limits. |
| Largest single input file | TBD | Upload strategy: chunked HTTP vs. shared-storage-only vs. direct-to-object-store. |
| Largest single run input set | TBD | Workspace quota, disk sizing, whether inputs are copied or bind-mounted. |
| Largest run output set | TBD | Packaging strategy - zipping a multi-TB output is not viable. |
| Total artifact storage at 12 months | TBD | Volume sizing, retention policy, when MinIO becomes necessary. |
| Retention window for run outputs | TBD | Janitor policy, researcher expectations. |
| Log volume per task | TBD | Log storage backend, streaming design, truncation policy. |

## Explicit consequences to revisit once the numbers exist

- **If the largest input exceeds a few GB**, HTTP upload through the API is the
  wrong primary path. Prefer shared-storage references plus a chunked upload
  fallback, and document the cutover size.
- **If output sets exceed tens of GB**, `run_output_package` (a single zip) must
  become optional, with a manifest plus per-file download as the default.
- **If p95 task duration exceeds a few hours**, worker leases and deployment
  upgrades must tolerate long-running containers - draining, not killing.
- **If runs per day exceed a few thousand**, revisit the Postgres queue decision
  with a measured benchmark, not a guess.

## Service levels

| Item | Target |
| --- | --- |
| API availability during working hours | TBD |
| Planned maintenance window | TBD |
| Acceptable queue latency (submit to task start, idle system) | TBD |
| RPO (max acceptable data loss) | TBD |
| RTO (max acceptable restore time) | TBD |

Document 06 says backup and restore must be tested. Without RPO/RTO the test
has no pass condition. Add both to the Phase 7 acceptance criteria.

## Resource governance

Not addressed anywhere in 01-09. A shared lab VM needs it:

- Max concurrent runs per user.
- Max concurrent tasks globally, and per runtime environment.
- Per-user storage quota, in addition to the per-run workspace quota.
- Fair scheduling so one researcher's 500-task fan-out does not starve others.
  A bare `priority` integer on `run_tasks` is not a policy.
- Task classes for large-memory or GPU work, if applicable.
- Behavior when a quota is exceeded: reject at submit, or queue as `blocked`.

## Data governance and compliance

This is the most serious omission for an institutional bioinformatics platform.
Documents 06 and 08 cover a security baseline and doc hygiene, but nothing
covers the data itself.

Decisions required:

- **Data classification.** Will the platform hold human-derived or otherwise
  identifiable data? If yes, everything below is mandatory rather than optional.
- **Encryption at rest** for the database and the artifact volume, and the key
  custody story.
- **Encryption in transit** including between containers if they cross hosts.
- **Access logging for reads.** Document 06 audits "delete artifact" but not
  *download* artifact. For regulated data, reads must be audited too.
- **Data minimisation and deletion.** A verifiable delete path (database rows,
  artifact bytes, backups, shared-storage copies, container logs) and a stated
  time to completion. `deleted_at` plus a janitor is not a deletion guarantee
  while backups exist.
- **Ethics / DPIA / information-governance approval** before production data.
- **Data residency** and whether any component may call an external service.
  This directly constrains the AI Designer decision (row 16 of
  [10-feature-parity-and-scope.md](10-feature-parity-and-scope.md)): sending
  workflow content to a third-party LLM API is a data-egress event.
- **Retention obligations** that may conflict with TTL cleanup - some funders
  require keeping outputs for years.
- **Shared-storage boundary.** Allowlisted roots are mounted institutional
  storage. Who is accountable for what BioPipeline2 writes into them, and does
  the platform respect the underlying POSIX permissions of the requesting user,
  or does it write as a single service account? The current design writes as the
  service account, which is an authorisation bypass in disguise. Decide and
  document.

## Environment constraints

- Is the production VM allowed outbound internet access? If not, task images and
  Python packages need an internal registry and mirror, and
  `runtime_environments` image builds cannot happen on the box.
- Is Docker permitted, or is rootless Podman mandatory?
- Is there an institutional SSO/LDAP that must be supported, and by when? "Later
  SSO" in document 05 is not a plan if the institution requires it at launch.
- Is there an institutional secret manager, backup service, or observability
  stack to integrate with rather than self-host?
- VM specification: CPU, RAM, disk, and whether disk can grow.
