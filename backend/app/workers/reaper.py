"""The reaper: the process that makes failures converge.

Every other process in the system is optimistic. A worker assumes it will
finish what it claimed; a run assumes its tasks will report back. The reaper
exists for when that does not happen, and it owns the transitions no optimistic
process can perform:

* **Expired leases.** A worker that died still holds tasks. Nobody but the
  reaper can take them back, because the worker that would release them is
  precisely the one that is gone.
* **Cancellations.** A run in ``cancel_requested`` whose tasks have all stopped
  has to reach ``cancelled``. The worker that held the last running task may
  have died between stopping it and recording the fact.
* **Dead workers.** A worker whose heartbeat stopped is marked stopped, so
  operators see three live workers rather than thirty historical ones.
* **Retention.** Artifacts past their expiry are purged, workspaces removed and
  the environment generations no run can still reach reclaimed, which is what
  keeps the disk from filling.

Each sweep is idempotent and independent. A reaper that crashes halfway leaves
the system in a state the next sweep handles, which is the property that lets it
be restarted freely.
"""

from __future__ import annotations

import logging
import signal
import threading
import uuid
from dataclasses import dataclass, field
from types import FrameType

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.application.environments import reclaim
from app.application.runs import advance_run
from app.application.uploads import staging_key
from app.infrastructure.artifacts import PosixArtifactStore
from app.infrastructure.db.claiming import reclaim_expired_leases
from app.settings import Settings

logger = logging.getLogger("biopipeline2.reaper")


@dataclass(slots=True)
class SweepReport:
    """What one pass changed. Every field is a metric worth alerting on."""

    leases_requeued: list[uuid.UUID] = field(default_factory=list)
    leases_failed: list[uuid.UUID] = field(default_factory=list)
    runs_converged: list[uuid.UUID] = field(default_factory=list)
    workers_reaped: list[str] = field(default_factory=list)
    artifacts_purged: int = 0
    artifacts_missing: int = 0
    workspaces_expired: int = 0
    uploads_expired: int = 0
    generations_reclaimed: int = 0

    @property
    def changed(self) -> bool:
        return bool(
            self.leases_requeued
            or self.leases_failed
            or self.runs_converged
            or self.workers_reaped
            or self.artifacts_purged
            or self.workspaces_expired
            or self.uploads_expired
            or self.generations_reclaimed
        )

    def summary(self) -> str:
        parts = []
        if self.leases_requeued:
            parts.append(f"{len(self.leases_requeued)} task(s) requeued")
        if self.leases_failed:
            parts.append(f"{len(self.leases_failed)} task(s) failed as poison")
        if self.runs_converged:
            parts.append(f"{len(self.runs_converged)} run(s) converged")
        if self.workers_reaped:
            parts.append(f"{len(self.workers_reaped)} worker(s) reaped")
        if self.artifacts_purged:
            parts.append(f"{self.artifacts_purged} artifact(s) purged")
        if self.artifacts_missing:
            parts.append(f"{self.artifacts_missing} artifact(s) already gone")
        if self.workspaces_expired:
            parts.append(f"{self.workspaces_expired} workspace(s) expired")
        if self.uploads_expired:
            parts.append(f"{self.uploads_expired} upload(s) expired")
        if self.generations_reclaimed:
            parts.append(f"{self.generations_reclaimed} environment generation(s) reclaimed")
        return ", ".join(parts) or "nothing to do"


def reclaim_leases(session: Session, *, poison_limit: int) -> SweepReport:
    """Take back tasks whose lease expired, and advance their runs."""
    report = SweepReport()
    for task_id, status in reclaim_expired_leases(session, poison_limit=poison_limit):
        if status == "failed":
            report.leases_failed.append(task_id)
        else:
            report.leases_requeued.append(task_id)

    # A reclaimed task changes its run's aggregate, and a poisoned one may
    # have just failed the run. Neither is visible until the run is advanced.
    if report.leases_requeued or report.leases_failed:
        affected = session.execute(
            text("SELECT DISTINCT run_id FROM run_tasks WHERE id = ANY(:ids)"),
            {"ids": [*report.leases_requeued, *report.leases_failed]},
        ).scalars()
        for run_id in affected:
            advance_run(session, run_id)
    return report


def close_lost_attempts(session: Session) -> int:
    """Mark attempts of reclaimed tasks as lost.

    An attempt left ``running`` forever misattributes a task's history: it
    looks as though the work is still going when the worker is long gone.
    """
    closed = session.execute(
        text(
            """
            UPDATE run_task_attempts a
            SET status = 'lost', finished_at = now()
            FROM run_tasks t
            WHERE a.task_id = t.id
              AND a.status = 'running'
              AND a.finished_at IS NULL
              AND t.claimed_by IS NULL
            RETURNING a.id
            """
        )
    ).scalars()
    return len(list(closed))


def converge_cancellations(session: Session) -> list[uuid.UUID]:
    """Finish runs whose cancellation has taken effect.

    The worker holding the last running task cannot be relied on to record
    this: it may have died between stopping the container and reporting. So a
    run whose tasks have all stopped is converged here, by the actor the
    lifecycle machine assigns to the transition.
    """
    ready = session.execute(
        text(
            """
            SELECT r.id
            FROM runs r
            WHERE r.status = 'cancel_requested'
              AND NOT EXISTS (
                  SELECT 1 FROM run_tasks t
                  WHERE t.run_id = r.id
                    AND t.status IN ('created', 'queued', 'claimed', 'running',
                                     'retry_wait')
              )
            """
        )
    ).scalars()

    converged: list[uuid.UUID] = []
    for run_id in list(ready):
        if advance_run(session, run_id) == "cancelled":
            converged.append(run_id)
    return converged


def reap_dead_workers(session: Session, *, stale_seconds: int) -> list[str]:
    """Mark workers whose heartbeat stopped.

    Cosmetic on its own -- the lease is what actually protects the work -- but
    a registry full of workers that died months ago makes it impossible to see
    at a glance how many are really running.
    """
    reaped = session.execute(
        text(
            """
            UPDATE workers
            SET status = 'stopped'
            WHERE status IN ('active', 'starting', 'draining')
              AND last_heartbeat_at < now() - make_interval(secs => :stale)
            RETURNING id
            """
        ),
        {"stale": stale_seconds},
    ).scalars()
    return list(reaped)


def purge_expired_artifacts(
    session: Session, store: PosixArtifactStore, *, limit: int = 200
) -> tuple[int, int]:
    """Delete the bytes of expired artifacts, then record that they are gone.

    Bytes first, then the row -- the same ordering as promotion, for the same
    reason. A row marked purged whose bytes survive is a lie that leaks disk;
    bytes deleted before the row is marked merely means the next sweep finds
    nothing to delete and says so.

    ``purged_at`` is what makes deletion *verifiable* rather than merely
    recorded, which is the distinction ADR 0012 rests on.
    """
    due = session.execute(
        text(
            """
            SELECT id, storage_key FROM artifacts
            WHERE deleted_at IS NULL
              AND purged_at IS NULL
              AND expires_at IS NOT NULL
              AND expires_at < now()
            ORDER BY expires_at
            LIMIT :limit
            """
        ),
        {"limit": limit},
    ).all()

    purged = 0
    missing = 0
    for row in due:
        if store.delete(row.storage_key):
            purged += 1
        else:
            # Already gone: a previous sweep was interrupted between the
            # delete and the update, or an operator removed it. Marking it
            # purged is still correct.
            missing += 1
        session.execute(
            text(
                "UPDATE artifacts SET deleted_at = COALESCE(deleted_at, now()), "
                "purged_at = now() WHERE id = :i"
            ),
            {"i": row.id},
        )
    return purged, missing


def expire_workspaces(session: Session, *, limit: int = 100) -> int:
    """Mark workspaces past their expiry.

    Only the marking happens here. Removing the directory belongs to whichever
    host holds it, and a reaper on another host cannot reach it.
    """
    expired = session.execute(
        text(
            """
            UPDATE workspaces
            SET status = 'expired'
            WHERE id IN (
                SELECT id FROM workspaces
                WHERE status = 'active'
                  AND deleted_at IS NULL
                  AND expires_at IS NOT NULL
                  AND expires_at < now()
                LIMIT :limit
            )
            RETURNING id
            """
        ),
        {"limit": limit},
    ).scalars()
    return len(list(expired))


def expire_uploads(session: Session, store: PosixArtifactStore, *, limit: int = 200) -> int:
    """Abandon uploads nobody finished, and release the disk they were holding.

    A chunked upload that is started and never completed holds disk and a
    storage key indefinitely. With multi-gigabyte inputs, a handful of
    abandoned uploads is a real amount of space.

    Marking the row and leaving the bytes is the version of this that looks
    finished and reclaims nothing, so the staging file goes too. The row is
    flipped first, because a file deleted under a row that still says `open`
    would have a client resuming into a hole. The cost of that order is that a
    delete which fails leaves bytes nothing will select again; the opposite
    order costs correctness, which is the more expensive of the two.
    """
    expired = session.execute(
        text(
            """
            UPDATE uploads
            SET status = 'expired'
            WHERE id IN (
                SELECT id FROM uploads
                WHERE status = 'open' AND expires_at < now()
                LIMIT :limit
            )
            RETURNING id
            """
        ),
        {"limit": limit},
    ).scalars()
    ids = list(expired)
    for upload_id in ids:
        store.delete(staging_key(upload_id))
    return len(ids)


class Reaper:
    """One reaper process.

    Several may run at once without harm: every sweep is a conditional update,
    so two reapers racing produce the same end state as one. That is
    deliberate -- requiring exactly one would need leader election, and the
    failure mode of *no* reaper is far worse than the cost of a duplicate.
    """

    def __init__(
        self,
        engine: Engine,
        settings: Settings,
        *,
        store: PosixArtifactStore | None = None,
        interval_seconds: int = 30,
    ) -> None:
        self.engine = engine
        self.settings = settings
        self.sessions = sessionmaker(bind=engine, expire_on_commit=False)
        self.store = store or PosixArtifactStore(settings.artifact_root)
        self.interval = interval_seconds
        self._stopping = threading.Event()

    def sweep(self) -> SweepReport:
        """One full pass. Idempotent, so a crash mid-sweep is recoverable."""
        with self.sessions() as session:
            report = reclaim_leases(session, poison_limit=self.settings.task_poison_limit)
            close_lost_attempts(session)
            report.runs_converged = converge_cancellations(session)
            report.workers_reaped = reap_dead_workers(
                session,
                # Generous: a worker is dead to us long after its lease
                # expires, and reaping a live-but-slow worker's registration
                # would be confusing without protecting anything.
                stale_seconds=max(self.settings.task_lease_seconds * 5, 600),
            )
            purged, missing = purge_expired_artifacts(session, self.store)
            report.artifacts_purged = purged
            report.artifacts_missing = missing
            report.workspaces_expired = expire_workspaces(session)
            report.uploads_expired = expire_uploads(session, self.store)
            reclaimed = reclaim(
                session,
                root=self.settings.environment_root,
                grace_hours=self.settings.environment_generation_grace_hours,
            )
            report.generations_reclaimed = reclaimed.removed + reclaimed.already_gone
            for path in reclaimed.refused:
                # Loud, because it means a row says a generation lives
                # somewhere that is not the environment root, and the sweep
                # declined to act on it. Nothing reclaims that disk until
                # somebody looks.
                logger.warning("generation path outside the environment root: %s", path)
            session.commit()
        return report

    def install_signal_handlers(self) -> None:
        def stop(signum: int, _frame: FrameType | None) -> None:
            logger.info("signal %s received; stopping", signum)
            self._stopping.set()

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)

    def run_forever(self, *, max_sweeps: int | None = None) -> int:
        """Sweep until stopped. Returns the number of sweeps performed."""
        sweeps = 0
        while not self._stopping.is_set():
            if max_sweeps is not None and sweeps >= max_sweeps:
                break
            sweeps += 1
            try:
                report = self.sweep()
            except Exception:
                logger.exception("sweep failed")
            else:
                if report.changed:
                    logger.info("sweep: %s", report.summary())
            self._stopping.wait(self.interval)
        return sweeps


def main() -> int:  # pragma: no cover - process entry point
    from sqlalchemy import create_engine

    from app.settings import load_settings

    logging.basicConfig(
        level=logging.INFO,
        format='{"level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
    )
    settings = load_settings()
    engine = create_engine(str(settings.database_url), pool_pre_ping=True)
    reaper = Reaper(engine, settings)
    reaper.install_signal_handlers()
    logger.info("reaper started")
    reaper.run_forever()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
