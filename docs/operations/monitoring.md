# What to watch, and when to worry

A number nobody would act on is noise. Every reading below exists because some
failure is invisible without it — and the most important ones are invisible
*by nature*, because they are things that fail to happen. A dead scheduler
produces no runs, and an absent run raises no alarm.

## Where the numbers are

`GET /api/v1/admin/metrics`, admin session required, and the Admin screen's
**Right now** panel renders the same reading with the thresholds already
applied. It is computed on request in a single statement; poll it as often as
you like.

Deliberately not Prometheus. A deployment is one VM with five to twenty users
(ADR 0006); a scrape endpoint, a time-series database and a dashboard would be
more operational surface than the thing they watch. If this platform ever
grows a fleet, that is the moment to add one — not before.

## The thresholds

| Reading | Worry when | Because |
| --- | --- | --- |
| `oldest_queued_seconds` | > 900 | **The one to alert on.** Nothing has claimed the oldest task for fifteen minutes: no worker is running, every worker is full of long tasks, or the admission budget is smaller than the work being submitted. Queue *depth* alone means nothing — a long queue is a busy afternoon. |
| `workers_stale` | > 0 | A worker stopped its heartbeat and still holds leases. The reaper will reclaim them after `task_lease_seconds`, but this is the earlier window, when work has quietly stopped and nobody has been told. |
| `schedules_overdue` | > 0 | A schedule whose firing time passed and stayed passed. The scheduler is dead or wedged. Nothing else in the system notices, because the symptom is a run that does not exist. |
| `deliveries_failed` | > 0 | A delivery gave up after `delivery_max_attempts`. The failures that survive five tries are configuration — an unmounted share, a permission — not weather. Needs a person. |
| `artifacts_awaiting_purge` | > 100 sustained | Expired outputs still on disk mean the reaper is not running. The first symptom of that is a full volume, days later. |
| `artifact_root_free_bytes` | < 10 GiB | A full artifact root fails every promotion, and a failed promotion fails the run that produced it. |
| `workers_draining` | > 0 for hours | Fine during an upgrade, and only during one. Otherwise something stopped a worker and it is waiting on a task that will not end. |
| `runs_failed_24h` | your own judgement | Not an alert. A pipeline that fails is a scientific result as often as an operational one; watch the trend, not the number. |

A minimal check, from cron, with no monitoring stack at all:

```bash
curl -fsS --cookie "$SESSION" https://<host>/api/v1/admin/metrics \
  | jq -e '.oldest_queued_seconds < 900 and .workers_stale == 0 and .schedules_overdue == 0'
```

## Logs

Every process writes one JSON object per line to stdout, and systemd collects
it:

```bash
journalctl -u biopipeline2-api -f
journalctl -u 'biopipeline2-worker@*' --since '1 hour ago'
journalctl -u biopipeline2-reaper --since today | jq -r 'select(.level != "INFO")'
```

Each line carries `time`, `level`, `process`, `logger` and `message`, plus
whichever of `request_id`, `run_id`, `task_id`, `worker_id` and `schedule_id`
the event had. `request_id` is the one that matters when somebody reports a
failure: the API returns it in the `X-Request-Id` header and in the error the
browser displayed, so "it broke at about eleven" becomes a single line.

```bash
journalctl -u biopipeline2-api --since today | jq -r 'select(.request_id == "req_...")'
```

## Health and readiness

- `GET /health` — the process is up. Touches nothing, deliberately: a database
  outage must not make a supervisor kill otherwise-healthy processes and turn a
  recoverable problem into an outage.
- `GET /ready` — it can actually serve. Checks the database and each storage
  root, answers `503` when any of them is not there, and names the one that
  failed.

Both are unauthenticated, because a reverse proxy and a container runtime
cannot present a session, and both say as little as possible for the same
reason.

## Storage drift

The weekly `biopipeline2-reconcile.timer` compares the database against the
disks and fails the unit if any row promises bytes that are gone:

```bash
systemctl status biopipeline2-reconcile.service
journalctl -u biopipeline2-reconcile.service --since '8 days ago'
```

Orphans — directories nothing points at — are reported and do not fail the
unit. See [backup-and-restore.md](backup-and-restore.md) for why a healthy
deployment has some, and how to reclaim them.

## What is not monitored, and why

**Per-task resource usage.** A task's container is given a CPU and memory
limit at launch and its exit is recorded; sampling what it used in between
would need a metrics agent, and nothing in the platform would act on the
answer.

**The database's own health.** PostgreSQL has better tooling than anything
this platform could offer; point it at whatever the institution already uses.

**Audit volume.** `audit_events` grows without bound and nothing prunes it,
because [ADR 0001](../../migration/docs/adr/0001-data-governance-and-classification.md)
has not yet said how long these records must be kept. Watch the table's size
if the deployment is busy; the answer is a decision, not a knob.
