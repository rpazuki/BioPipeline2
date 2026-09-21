"""The numbers an operator would be woken for.

Deliberately not a time series and deliberately not Prometheus. A deployment
is one VM with five to twenty users (ADR 0006); a scrape endpoint plus a
metrics stack is more operational surface than the thing it watches. This is
the current state, computed on request, cheap enough to poll from cron and
readable by a person at three in the morning.

The rule for what belongs here: a number nobody would act on is noise. Queue
depth alone is not actionable -- a long queue is a busy afternoon. *The oldest
queued task's age* is: past a threshold it means nothing is claiming, which is
a worker that died, a database that is refusing, or an admission budget too
small for the work. Each number below exists because some failure is invisible
without it.
"""

from __future__ import annotations

import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(frozen=True, slots=True)
class Snapshot:
    """One reading. Every field is something an alert could fire on."""

    # Work waiting. The age is the signal; the depth is the context.
    tasks_queued: int = 0
    oldest_queued_seconds: int = 0
    tasks_running: int = 0
    tasks_retrying: int = 0

    # The fleet. A worker is stale when its heartbeat stopped but the reaper
    # has not yet declared it dead -- the window in which work is quietly not
    # being done.
    workers_active: int = 0
    workers_draining: int = 0
    workers_stale: int = 0

    # Outcomes, for the shape of a day rather than for alerting.
    runs_succeeded_24h: int = 0
    runs_failed_24h: int = 0

    # Delivery to shared storage retries by itself; what needs a person is a
    # delivery that has stopped retrying.
    deliveries_pending: int = 0
    deliveries_failed: int = 0

    # Janitor lag. Artifacts past their expiry that still have bytes mean the
    # reaper is not running, and the first symptom of that is a full disk.
    artifacts_awaiting_purge: int = 0
    uploads_open: int = 0

    # A schedule whose firing time has passed and stayed passed means the
    # scheduler is dead. Nothing else in the system notices.
    schedules_overdue: int = 0

    # Disk, from the host this process runs on. A single-VM deployment shares
    # these roots with the workers; a split one must read them where the
    # workers are.
    artifact_root_free_bytes: int = 0
    workspace_root_free_bytes: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


def _free_bytes(path: Path) -> int:
    try:
        return int(shutil.disk_usage(path).free)
    except OSError:
        # A root that is not mounted answers nothing rather than crashing the
        # endpoint an operator is using to find out why.
        return 0


def snapshot(
    session: Session,
    *,
    stale_after_seconds: int,
    overdue_after_seconds: int,
    artifact_root: Path | str,
    workspace_root: Path | str,
) -> Snapshot:
    """Read every number in one pass.

    One statement rather than a dozen round trips, because this is called by
    a poller and by a screen that refreshes.
    """
    row = session.execute(
        text(
            """
            SELECT
              (SELECT count(*) FROM run_tasks WHERE status IN ('created', 'queued'))
                AS tasks_queued,
              COALESCE((
                SELECT EXTRACT(EPOCH FROM now() - min(created_at))
                FROM run_tasks WHERE status IN ('created', 'queued')
              ), 0) AS oldest_queued_seconds,
              (SELECT count(*) FROM run_tasks WHERE status = 'running') AS tasks_running,
              (SELECT count(*) FROM run_tasks WHERE status = 'retry_wait') AS tasks_retrying,
              (SELECT count(*) FROM workers WHERE status = 'active'
                 AND last_heartbeat_at >= now() - make_interval(secs => :stale))
                AS workers_active,
              (SELECT count(*) FROM workers WHERE status = 'draining') AS workers_draining,
              (SELECT count(*) FROM workers WHERE status IN ('active', 'starting')
                 AND last_heartbeat_at < now() - make_interval(secs => :stale))
                AS workers_stale,
              (SELECT count(*) FROM runs WHERE status = 'succeeded'
                 AND finished_at > now() - interval '24 hours') AS runs_succeeded_24h,
              (SELECT count(*) FROM runs WHERE status = 'failed'
                 AND finished_at > now() - interval '24 hours') AS runs_failed_24h,
              (SELECT count(*) FROM run_deliveries WHERE status = 'pending')
                AS deliveries_pending,
              (SELECT count(*) FROM run_deliveries WHERE status = 'failed') AS deliveries_failed,
              (SELECT count(*) FROM artifacts WHERE purged_at IS NULL
                 AND expires_at IS NOT NULL AND expires_at < now())
                AS artifacts_awaiting_purge,
              (SELECT count(*) FROM uploads WHERE status = 'open') AS uploads_open,
              (SELECT count(*) FROM schedules WHERE status = 'active'
                 AND next_fire_at IS NOT NULL
                 AND next_fire_at < now() - make_interval(secs => :overdue))
                AS schedules_overdue
            """
        ),
        {"stale": stale_after_seconds, "overdue": overdue_after_seconds},
    ).one()

    return Snapshot(
        tasks_queued=int(row.tasks_queued),
        oldest_queued_seconds=int(row.oldest_queued_seconds),
        tasks_running=int(row.tasks_running),
        tasks_retrying=int(row.tasks_retrying),
        workers_active=int(row.workers_active),
        workers_draining=int(row.workers_draining),
        workers_stale=int(row.workers_stale),
        runs_succeeded_24h=int(row.runs_succeeded_24h),
        runs_failed_24h=int(row.runs_failed_24h),
        deliveries_pending=int(row.deliveries_pending),
        deliveries_failed=int(row.deliveries_failed),
        artifacts_awaiting_purge=int(row.artifacts_awaiting_purge),
        uploads_open=int(row.uploads_open),
        schedules_overdue=int(row.schedules_overdue),
        artifact_root_free_bytes=_free_bytes(Path(artifact_root)),
        workspace_root_free_bytes=_free_bytes(Path(workspace_root)),
    )
