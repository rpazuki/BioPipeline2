# Execution Model

Last reviewed: 2026-09-18
Applies to: BioPipeline2 0.1.0

## The problem this solves

The workload spans four orders of magnitude. Measured from a real deployment
(2,178 task specs):

| | duration |
| --- | --- |
| minimum | 0.8 s |
| average | 24.8 s |
| maximum | 47.8 s |

That is plate-reader parsing and curve fitting. The planned workload includes
RNA-seq alignment and counting, which runs for **hours to a day** per sample,
reads and writes gigabytes, and will exhaust a single VM if two run at once.

So the platform must run short tasks in parallel and heavy tasks effectively
alone, without the operator maintaining two queues or the author choosing a
queue by hand.

## Admission control, not a serial queue

Each task declares a resource **request**: CPU millicores, memory bytes, a wall
time limit, and optionally `exclusive`. A worker claims a task only if its
request fits the budget not already committed to running tasks.

Sequential execution of heavy work falls out of the arithmetic. A task that
requests the whole budget cannot be admitted while anything else holds
resources, and nothing else can be admitted while it runs. No separate mode, no
manual queue selection.

```
budget:  4000 mCPU, 12 GiB, max 4 tasks

  small(500m, 1G) + small(500m, 1G) + small(500m, 1G)   -> all three run
  align(4000m, 12G)                                      -> runs alone
  align running -> nothing else admitted
```

Configured by `BP_WORKER_BUDGET_CPU_MILLICORES`,
`BP_WORKER_BUDGET_MEMORY_BYTES`, and `BP_WORKER_MAX_CONCURRENT_TASKS`. Set them
**below** the host's real capacity: the API, the database, and the operating
system need headroom a worker does not know about.

Implementation: [`app/infrastructure/db/claiming.py`](../../backend/app/infrastructure/db/claiming.py).
The budget check runs inside the claiming transaction, so concurrent workers
cannot jointly over-commit. `FOR UPDATE SKIP LOCKED` keeps two workers off the
same row.

### Task classes

`small`, `standard`, `large`, `exclusive` are conventional names for request
profiles. The class is a label; the request columns are what the claim query
reads. A pipeline revision sets them per stage. (Nothing here involves the
`scheduler` process, which starts runs on a clock and never looks at a task.)

### Starvation

Admission control alone lets a steady trickle of small tasks postpone a large
one forever. The claim query therefore skips a task if an older queued task
exists that does not currently fit, unless the younger task would also fit
alongside it — so a waiting alignment job drains the queue ahead of itself
rather than waiting indefinitely.

## Leases, because tasks outlive workers

A task held by a worker carries a lease, not a flag. The worker renews it on a
heartbeat well below the lease TTL; the reaper requeues anything whose lease has
expired.

Sizing matters and is easy to get wrong: **the lease TTL must exceed the longest
pause in the worker loop, not the longest task.** A day-long alignment renews
its lease hundreds of times. Setting the TTL to a day would mean a crashed
worker strands its task for a day.

Defaults: `BP_TASK_LEASE_SECONDS=120`, `BP_TASK_HEARTBEAT_SECONDS=30`.

A task whose lease expires more than `BP_TASK_POISON_LIMIT` times without a
clean outcome is failed rather than requeued. Without that a task that never
reports back cycles forever.

## Cancellation

`cancel_requested_at` on the run is data, not just a status, so a worker
observes it by polling its own tasks on the heartbeat. On cancel the worker
sends SIGTERM, waits `BP_TASK_CANCEL_GRACE_SECONDS`, then SIGKILL.

**The reaper owns the final transition**, not the worker: the worker holding the
task may already be gone, and a cancel must converge either way. This is
encoded in `RUN_MACHINE` — `cancel_requested -> cancelled` is not available to
the `WORKER` actor.

## Upgrades

A day-long task means an upgrade cannot simply wait for the queue to drain.
The supported sequence:

1. Mark workers `draining` — they stop claiming but keep running what they hold.
2. Migrate the database. Safe because migrations follow expand/contract, so the
   old code keeps working against the new schema.
3. Deploy the new API and workers.
4. Old workers finish their tasks and exit.

Tasks therefore survive a deployment. What is *not* supported is a migration
that breaks the running code's assumptions — hence the expand/contract rule in
[`migration/12-testing-ci-and-release.md`](../../migration/12-testing-ci-and-release.md).

## Environment generations

Admins install packages into a shared environment as part of normal work, so
the plan's immutable pinned images were the wrong shape: they turn every `pip
install` into an image build. The environment is mutable, and isolation comes
from **generations** instead (ADR 0028).

An install copies the current generation, installs into the copy, inventories
and hashes it, and only then moves `runtime_environments.current_generation_id`.
A run pins a generation at submission and every task of that run executes
against it. Nothing mutates a generation once it is built, so a `pip install`
cannot change behaviour underneath a task that has been running for two days —
and the run records exactly what it used, without an image registry.

Two details are load-bearing:

- **Every generation is mounted at the same container path**, `/env`, and built
  there too. A virtualenv embeds absolute paths, so it works only where it was
  built; one path for all of them is what makes copying one safe.
- **The copy is a real copy.** pip rewrites files in place, so a hardlinked
  clone would corrupt the generation it came from. Disk grows per install, and
  the janitor is meant to reclaim unreferenced generations — that sweep is not
  written yet.

A task's container gets the generation read-only, with its `site-packages`
ahead of the configured library directories on `PYTHONPATH`. Read-only,
because a task that can write to the environment can change what every later
task imports.

**Editable installs.** The real install history shows `labUtils` installed
editable from a working tree alongside PyPI and git installs. An editable
install is a link to source, so no generation can capture it: two runs against
the same generation can execute different code if the library is edited
between them. pip reports it, the generation carries the flag, and every run
pinning it is marked non-reproducible with the package and the path named —
rather than claiming provenance it cannot deliver (G94).

## Outputs

Packaging an output set into a single archive stops being useful somewhere
above a couple of gigabytes. Above `BP_PACKAGE_OUTPUTS_MAX_TOTAL_BYTES` the
janitor writes a manifest instead and the UI offers per-file download.

Outputs are delivered by download and/or copied into an allowlisted shared
storage root. Delivery is tracked per output in `run_deliveries` with its own
status and retry, because it can fail after the run has already succeeded.

The copying is done by the **courier** (`app/workers/courier.py`), a process of
its own. Not the worker, where a multi-gigabyte copy would hold an execution
slot that admission control has reserved for containers; and not the reaper,
where it would sit in front of lease reclamation and leave a dead worker's
tasks stuck until it finished. A delivery is claimed with `FOR UPDATE SKIP
LOCKED` and leased through `next_attempt_at`, so more than one courier may run.

It copies rather than links — the artifact store is the platform's volume and
the share is somebody else's — writes through a temporary name so a researcher
never opens a file that is still arriving, and **never overwrites** anything
already at the target. A transient failure such as an unmounted share is
retried with a backoff; a configuration failure such as a root registered
read-only is not, because retrying will not change it.

## Failure retention

Failed runs are kept. The real deployment's database contains 164 jobs, all
`succeeded`, because the operator deleted every failed job by hand to keep the
list readable. That is a workflow the tool imposed rather than a preference:
the UI must make failures filterable and archivable so the evidence survives.
Diagnosing an intermittent failure is impossible once the failures are gone.
