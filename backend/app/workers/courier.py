"""The courier: the process that carries outputs to shared storage.

Its own process, and the reasoning is worth keeping. Delivery is a **copy of
arbitrarily many gigabytes**, and everything else that could host it is
something that must stay responsive:

* In the **task worker**, a copy would hold an execution slot that admission
  control has reserved for running containers.
* In the **reaper**, it would sit in front of lease reclamation — a worker dies
  while a forty-gigabyte delivery is in progress, and every task it was holding
  stays stuck until the copy finishes.

So it is a fourth process, deliberately, on a deployment that runs three.

More than one may run at once. A delivery is claimed with `FOR UPDATE SKIP
LOCKED` and leased through `next_attempt_at`, the same shape as task claiming,
so correctness comes from the claim rather than from there being one courier.
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

from app.application.deliveries import DeliveryReport, deliver_one, due_delivery_ids
from app.infrastructure.artifacts import PosixArtifactStore
from app.observability import configure_logging
from app.settings import Settings

logger = logging.getLogger("biopipeline2.courier")


@dataclass(slots=True)
class RoundReport:
    """What one pass over the due deliveries did."""

    considered: int = 0
    delivered: list[str] = field(default_factory=list)
    failed: int = 0
    retrying: int = 0
    skipped: int = 0
    errors: int = 0
    more_due: bool = False

    def absorb(self, report: DeliveryReport) -> None:
        self.considered += 1
        if report.delivered:
            self.delivered.append(str(report.delivery_id))
        elif report.failed:
            self.failed += 1
        elif report.skipped:
            self.skipped += 1
        elif report.message:
            self.retrying += 1

    @property
    def changed(self) -> bool:
        return bool(self.delivered or self.failed or self.retrying or self.errors)

    def summary(self) -> str:
        parts = []
        if self.delivered:
            parts.append(f"{len(self.delivered)} delivered")
        if self.retrying:
            parts.append(f"{self.retrying} will be retried")
        if self.failed:
            parts.append(f"{self.failed} failed")
        if self.errors:
            parts.append(f"{self.errors} raised")
        return ", ".join(parts) or "nothing due"


class Courier:
    """One courier process."""

    def __init__(self, engine: Engine, settings: Settings) -> None:
        self.engine = engine
        self.settings = settings
        self.sessions = sessionmaker(bind=engine, expire_on_commit=False)
        self.store = PosixArtifactStore(settings.artifact_root)
        self.interval = settings.delivery_poll_seconds
        self._stopping = threading.Event()

    def round(self, *, now: datetime | None = None) -> RoundReport:
        """One pass. Each delivery gets its own transaction."""
        now = now or datetime.now(UTC)
        report = RoundReport()
        with self.sessions() as session:
            due = due_delivery_ids(session, now=now, limit=self.settings.delivery_batch_size)
        if len(due) >= self.settings.delivery_batch_size:
            report.more_due = True

        for delivery_id in due:
            try:
                with self.sessions() as session:
                    outcome = deliver_one(
                        session,
                        delivery_id,
                        store=self.store,
                        now=now,
                        lease_seconds=self.settings.delivery_lease_seconds,
                        max_attempts=self.settings.delivery_max_attempts,
                        retry_seconds=self.settings.delivery_retry_seconds,
                    )
                    session.commit()
            except Exception:
                # One delivery must never take the loop down. The transaction
                # is rolled back, so the lease goes with it and the next pass
                # tries again.
                logger.exception("delivery %s raised", delivery_id)
                report.errors += 1
                continue
            report.absorb(outcome)
            if outcome.delivered:
                logger.info("delivered %s to %s", delivery_id, outcome.target_path)
            elif outcome.message:
                logger.warning("delivery %s: %s", delivery_id, outcome.message)
        return report

    def install_signal_handlers(self) -> None:
        def stop(signum: int, _frame: FrameType | None) -> None:
            logger.info("signal %s received; stopping", signum)
            self._stopping.set()

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)

    def run_forever(self, *, max_rounds: int | None = None) -> int:
        rounds = 0
        while not self._stopping.is_set():
            if max_rounds is not None and rounds >= max_rounds:
                break
            rounds += 1
            try:
                report = self.round()
            except Exception:
                logger.exception("round failed")
                self._stopping.wait(self.interval)
                continue
            if report.changed:
                logger.info("round: %s", report.summary())
            if report.more_due:
                # A backlog of deliveries is worked through without waiting,
                # as the scheduler does with a backlog of windows.
                continue
            self._stopping.wait(self.interval)
        return rounds


def main() -> int:  # pragma: no cover - process entry point
    from sqlalchemy import create_engine

    from app.settings import load_settings

    configure_logging("courier")
    settings = load_settings()
    engine = create_engine(str(settings.database_url), pool_pre_ping=True)
    courier = Courier(engine, settings)
    courier.install_signal_handlers()
    logger.info("courier started, polling every %ss", courier.interval)
    courier.run_forever()
    logger.info("courier stopped")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
