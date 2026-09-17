"""The scheduler: the process that turns a clock into runs.

It owns no execution. A tick reads which schedules are due, and for each one
submits exactly the run a researcher would have submitted from the catalog --
so a scheduled run is claimed, executed, delivered and displayed by the same
machinery as any other, and nothing downstream needs to know a clock was
involved.

**More than one may run at once.** That is the point of
``schedule_fires (schedule_id, fire_at)``: the window, not the process, is
what gets claimed. Document 06 weighed leader election against the constraint
and chose the constraint, because the failure mode of a leader that has quietly
died is that *nothing* runs, and nobody finds out until the morning.

Each tick is independent and every step of it is idempotent, so the scheduler
can be killed at any moment. The one thing it must never do is let a single bad
schedule stop it: a publication that was archived under a schedule's feet
should pause that schedule, not silence every other one on the machine.
"""

from __future__ import annotations

import logging
import signal
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import FrameType

from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from app.application.schedules import FireReport, due_schedule_ids, fire_due
from app.domain.materialise import FanOutEnumerator
from app.infrastructure.fanout import DirectoryFanOut
from app.infrastructure.mounts import readable_roots
from app.settings import Settings

logger = logging.getLogger("biopipeline2.scheduler")


@dataclass(slots=True)
class TickReport:
    """What one pass over the due schedules did."""

    considered: int = 0
    runs_created: list[str] = field(default_factory=list)
    schedules_failed: int = 0
    schedules_paused: int = 0
    skipped: int = 0
    deferred: int = 0
    errors: int = 0
    more_due: bool = False
    """Work remains this tick could not reach; poll again without waiting."""

    def absorb(self, report: FireReport) -> None:
        self.considered += 1
        self.runs_created.extend(str(run_id) for run_id in report.created)
        self.schedules_failed += 1 if report.failed else 0
        self.schedules_paused += 1 if report.paused else 0
        self.skipped += report.skipped_overlap + report.skipped_catchup
        self.deferred += report.deferred
        self.more_due = self.more_due or report.more_due

    @property
    def changed(self) -> bool:
        return bool(
            self.runs_created
            or self.schedules_failed
            or self.schedules_paused
            or self.skipped
            or self.errors
        )

    def summary(self) -> str:
        parts = []
        if self.runs_created:
            parts.append(f"{len(self.runs_created)} run(s) created")
        if self.skipped:
            parts.append(f"{self.skipped} window(s) skipped")
        if self.deferred:
            parts.append(f"{self.deferred} window(s) deferred")
        if self.schedules_failed:
            parts.append(f"{self.schedules_failed} schedule(s) failed")
        if self.schedules_paused:
            parts.append(f"{self.schedules_paused} schedule(s) paused")
        if self.errors:
            parts.append(f"{self.errors} schedule(s) raised")
        return ", ".join(parts) or "nothing due"


class Scheduler:
    """One scheduler process."""

    def __init__(
        self,
        engine: Engine,
        settings: Settings,
        *,
        enumerate_fanout: FanOutEnumerator | None = None,
    ) -> None:
        self.engine = engine
        self.settings = settings
        self.sessions = sessionmaker(bind=engine, expire_on_commit=False)
        self.interval = settings.scheduler_poll_seconds
        if enumerate_fanout is None:
            # Resolved once, like the worker's mounts: the attested roots
            # change when an admin attests one, which is a deployment event,
            # not something worth a query on every window.
            with self.sessions() as session:
                enumerate_fanout = DirectoryFanOut(readable_roots(session))
        self.enumerate_fanout = enumerate_fanout
        self._stopping = threading.Event()

    def tick(self, *, now: datetime | None = None) -> TickReport:
        """One pass. Each schedule gets its own transaction.

        Short transactions on purpose: a schedule that fans out over a large
        directory takes real time to materialise, and holding a lock over
        every other schedule while it does would make one slow entry look like
        a dead scheduler.
        """
        now = now or datetime.now(UTC)
        report = TickReport()
        with self.sessions() as session:
            due = due_schedule_ids(session, now=now, limit=self.settings.scheduler_batch_size)
        if len(due) >= self.settings.scheduler_batch_size:
            report.more_due = True

        for schedule_id in due:
            try:
                with self.sessions() as session:
                    fired = fire_due(
                        session,
                        schedule_id,
                        now=now,
                        enumerate_fanout=self.enumerate_fanout,
                        grace_seconds=self.settings.scheduler_misfire_grace_seconds,
                        limit=self.settings.scheduler_max_catchup_runs,
                    )
                    session.commit()
            except Exception:
                # One schedule must never take the loop down with it. The
                # transaction is already rolled back by the context manager,
                # so the window stays unclaimed and the next tick retries it.
                logger.exception("schedule %s failed to fire", schedule_id)
                report.errors += 1
                continue
            report.absorb(fired)
            if fired.changed:
                logger.info("schedule %s: %s", schedule_id, fired.summary())
        return report

    def install_signal_handlers(self) -> None:
        def stop(signum: int, _frame: FrameType | None) -> None:
            logger.info("signal %s received; stopping", signum)
            self._stopping.set()

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)

    def run_forever(self, *, max_ticks: int | None = None) -> int:
        """Tick until stopped. Returns the number of ticks performed."""
        ticks = 0
        while not self._stopping.is_set():
            if max_ticks is not None and ticks >= max_ticks:
                break
            ticks += 1
            try:
                report = self.tick()
            except Exception:
                logger.exception("tick failed")
                self._stopping.wait(self.interval)
                continue
            if report.changed:
                logger.info("tick: %s", report.summary())
            if report.more_due:
                # A backlog is being worked through. Sleeping the full
                # interval here would make catching up take as long as the
                # outage did.
                continue
            self._stopping.wait(self.interval)
        return ticks


def main() -> int:  # pragma: no cover - process entry point
    from sqlalchemy import create_engine

    from app.settings import load_settings

    logging.basicConfig(
        level=logging.INFO,
        format='{"level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
    )
    settings = load_settings()
    engine = create_engine(str(settings.database_url), pool_pre_ping=True)
    scheduler = Scheduler(engine, settings)
    scheduler.install_signal_handlers()
    logger.info("scheduler started, polling every %ss", scheduler.interval)
    scheduler.run_forever()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
