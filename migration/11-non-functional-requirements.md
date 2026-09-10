# Non-Functional Requirements

Superseded in part by [15-premise-correction.md](15-premise-correction.md). The
original version of this document speculated about a bioinformatics data
platform holding human-derived data at TB scale. The platform holds no data
corpus (ADR 0001), and the numbers below are measured rather than guessed.

## Scale, measured

From the real deployment: 2,178 task specifications, 164 jobs, 33 run
workspaces.

| Dimension | Measured | Notes |
| --- | --- | --- |
| Task duration | min 0.8 s, mean 24.8 s, max 47.8 s | Plate-reader parsing and curve fitting |
| Fan-out width | max 58 tasks, typically 1-3 | Two-level: `variables` matrix times fan-out items |
| Run workspace | 99 MB over 33 runs, largest 31 MB | |
| Task log | ~31 KB average, 73 MB total over 2,342 files | |
| Published jobs | 8 | |
| Published runs | 31 | |
| Users | 5 | |
| Package installs | 19, mixing PyPI, git and editable local paths | |

## Scale, planned

RNA-seq alignment and counting. This is the workload that sizes the system, and
it is nothing like the measured one:

| Dimension | Target |
| --- | --- |
| Task duration | hours to 24 h per task |
| Single input | up to tens of GB per sample |
| Concurrency | heavy tasks must run **sequentially**; the VM cannot host two |
| Users | 5-20, one lab, one project |
| Deployment | one Linux VM, Docker |

## What those numbers decide

| Choice | Verdict |
| --- | --- |
| PostgreSQL as the queue | Comfortably sufficient. Nothing here approaches the throughput at which a broker earns its complexity. |
| Single VM | Sufficient, provided admission control keeps heavy work sequential. |
| HTTP upload as the primary input path | **No.** Fine for plate-reader CSVs, unworkable for FASTQ. Shared-storage selection is the primary path for large inputs; chunked upload remains the small-file case. |
| Zip packaging of outputs | Conditional. Above `BP_PACKAGE_OUTPUTS_MAX_TOTAL_BYTES` the janitor writes a manifest and the UI offers per-file download. |
| One timeout and memory profile | **No.** Four orders of magnitude in duration needs task classes and resource requests. See ADR 0029. |
| Lease TTL sized to task duration | **No.** The TTL must exceed the worker's longest *pause*, not the longest task, or a crashed worker strands a day-long job for a day. |
| Fair-share scheduling, per-user quotas | Not needed at 5-20 users. Resource admission control replaces them. |
| Notifications as low priority | **Revisit.** A researcher who submits an alignment and waits a day needs to be told it finished, and needs queue position while waiting. ADR 0014. |

## Service levels

| Item | Target |
| --- | --- |
| Availability | Working hours, best effort. No formal SLA at this scale. |
| Maintenance window | Any time, provided running tasks survive (worker draining) |
| Queue latency, idle system | Seconds |
| RPO | 24 h — the last nightly database dump |
| RTO | 4 h to a working system from a clean VM |

RPO and RTO are what give the restore rehearsal in document 06 a pass
condition. Artifact bytes are explicitly **not** covered by RPO: they are
transient by design, and a lost artifact means re-running a pipeline rather than
losing a record.

## Resource governance

Handled by admission control rather than quotas (ADR 0029):

- `BP_WORKER_BUDGET_CPU_MILLICORES`, `BP_WORKER_BUDGET_MEMORY_BYTES`,
  `BP_WORKER_MAX_CONCURRENT_TASKS` bound what the host commits at once.
- A task declares a request; it is claimed only if the request fits the
  uncommitted remainder. A task requesting the whole budget runs alone.
- Set budgets **below** real host capacity: the API, database and OS need
  headroom the scheduler does not model.
- Per-run workspace quota (`workspaces.quota_bytes`) still applies, and matters
  much more once RNA-seq intermediates exist.

Anti-starvation is a policy, not just a mechanism: the claim query refuses to
admit a task younger than the oldest task that does not fit, so a waiting
alignment drains the queue ahead of itself.

## Data handling

The platform holds no corpus (ADR 0001). What it does hold is transient, and the
requirements are about prompt disposal rather than protection of a store:

- Inputs and outputs are removed on a TTL; run records, parameters and logs
  survive for provenance (ADR 0012).
- `artifacts.purged_at` records that bytes are actually gone, distinguishing
  "withdrawn from view" from "destroyed".
- Artifact **reads** are audited (`artifact_access_events`). Kept on despite the
  light governance posture, because it costs almost nothing and retrofitting it
  is expensive.
- The data is not human-derived and not domain-restricted. No classification
  tiers, no encryption-at-rest mandate, no DPIA gate, no residency constraint.
- **If the platform is ever pointed at identifiable data, ADR 0001 must be
  superseded first.** Everything above changes in that case.

### The one unresolved boundary

Shared-storage roots are mounted institutional storage. Whether the platform
reads and writes them as the **requesting user** or as a **single service
account** is unanswered (ADR 0013), and a service account bypasses whatever
permissions that storage enforces. This matters more with RNA-seq, where the
storage is likely a sequencing facility's.

`shared_storage_roots.identity_mode` records the choice per root, and no
shared-storage access path is built until the ADR is accepted.

## Environment constraints

| Item | Decision |
| --- | --- |
| Container runtime | Docker (ADR 0008) |
| Host OS | Generic Linux VM; no Red Hat, Podman or SELinux specifics |
| Outbound internet | Assumed available. Pipelines already fetch models from `bigg.ucsd.edu`, and packages install from PyPI and GitHub. |
| SSO | Unresolved (ADR 0007). The schema supports it without change: `password_hash` is nullable and `auth_provider` exists. |
| Secret manager | None. The task contract assumes tasks need no secrets and enforces it (ADR 0023 open). |
| Path prefix | Required from the start, e.g. `/biopipeline` |
| Existing data paths | Windows (`H:\ROBOT_SCIENTIST\...`, `C:\Users\...`). Re-authoring must translate them; no importer will. |
