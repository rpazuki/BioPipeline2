"""The worker loop: claim, execute, record, repeat.

The structural decision here is where transactions begin and end. A task can
run for a day, so **no database transaction is held while a container runs**.
Each iteration is three short transactions with the long part outside them:

1. Claim a task and commit, so the lease is immediately visible to other
   workers and to the reaper.
2. Run the container, holding nothing.
3. Record the outcome, release whatever it unblocked, and commit.

A connection held open across a day-long task would exhaust the pool, block
schema changes, and make every lease look fresh to a reaper that cannot see
past it.

While a task runs, a separate thread renews the lease and watches for
cancellation. It needs its own session, because a SQLAlchemy Session is not
safe to share across threads.
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from types import FrameType

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.application.runs import advance_run, release_ready_tasks
from app.domain.enums import WorkerStatus
from app.domain.task_contract import ResourceLimits
from app.infrastructure.artifacts import PosixArtifactStore
from app.infrastructure.db.claiming import Budget, claim_next_task
from app.infrastructure.execution.docker import DockerAdapter
from app.infrastructure.mounts import shared_root_mounts
from app.infrastructure.workspace import create_workspace
from app.observability import configure_logging
from app.settings import Settings
from app.workers.executor import execute_task, reconcile_orphans

logger = logging.getLogger("biopipeline2.worker")


def worker_identity() -> str:
    """Stable within a process, distinct between processes.

    The pid alone is not enough: pids are reused, and a reclaimed lease must
    never be attributed to a different worker that happens to share one.
    """
    return f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"


@dataclass(slots=True)
class ClaimedTask:
    task_id: uuid.UUID
    run_id: uuid.UUID
    task_key: str
    stage_key: str
    task_spec: dict
    attempt: int
    limits: ResourceLimits


class LeaseKeeper:
    """Renews a task's lease and watches for cancellation while it runs.

    The lease TTL is sized against the worker's longest *pause*, not the
    longest task, so a day-long task renews hundreds of times. If this thread
    stops, the lease expires and the reaper requeues the task -- which is the
    intended behaviour when a worker has wedged.
    """

    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        task_id: uuid.UUID,
        worker_id: str,
        interval_seconds: int,
        lease_seconds: int,
        on_cancel: threading.Event,
        draining: threading.Event | None = None,
    ) -> None:
        self._sessions = sessions
        self._task_id = task_id
        self._worker_id = worker_id
        self._interval = interval_seconds
        self._lease = lease_seconds
        self._cancel = on_cancel
        # The drain flag is read here rather than acted on in the signal
        # handler: a handler runs on the main thread, possibly in the middle
        # of a database call, and writing from it is how a deployment turns
        # into a deadlock. The heartbeat is already a thread with a session.
        self._draining = draining or threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"lease-{task_id}", daemon=True)

    def __enter__(self) -> LeaseKeeper:
        self._thread.start()
        return self

    def __exit__(self, *_exception: object) -> None:
        self._stop.set()
        self._thread.join(timeout=self._interval + 5)

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                with self._sessions() as session:
                    renewed = session.execute(
                        text(
                            "UPDATE run_tasks SET "
                            "  lease_expires_at = now() + make_interval(secs => :ttl), "
                            "  heartbeat_at = now() "
                            "WHERE id = :t AND claimed_by = :w "
                            "RETURNING cancel_requested_at"
                        ),
                        {"ttl": self._lease, "t": self._task_id, "w": self._worker_id},
                    ).one_or_none()
                    session.execute(
                        text(
                            "UPDATE workers SET last_heartbeat_at = now(), status = :s "
                            "WHERE id = :w"
                        ),
                        # An operator upgrading needs to see the difference
                        # between a worker that is busy and one that is
                        # finishing its last task and then leaving. Both look
                        # identical from the queue.
                        {
                            "s": WorkerStatus.DRAINING
                            if self._draining.is_set()
                            else WorkerStatus.ACTIVE,
                            "w": self._worker_id,
                        },
                    )
                    session.commit()
                if renewed is None:
                    # The task is no longer ours: a reaper reclaimed it. Stop
                    # the work rather than racing whoever has it now.
                    logger.warning("lease lost for task %s", self._task_id)
                    self._cancel.set()
                    return
                if renewed.cancel_requested_at is not None:
                    self._cancel.set()
                    return
            except Exception:
                logger.exception(
                    "heartbeat failed",
                    extra={"task_id": self._task_id, "worker_id": self._worker_id},
                )


class Worker:
    """One worker process."""

    def __init__(
        self,
        engine: Engine,
        settings: Settings,
        *,
        adapter: DockerAdapter | None = None,
        worker_id: str | None = None,
    ) -> None:
        self.engine = engine
        self.settings = settings
        self.sessions = sessionmaker(bind=engine, expire_on_commit=False)
        self.worker_id = worker_id or worker_identity()
        self.adapter = adapter or DockerAdapter(
            image=settings.task_default_image,
            binary=settings.container_runtime,
            library_paths=tuple(str(path) for path in settings.task_library_paths),
        )
        # Resolved once at start-up rather than per task: the set changes when
        # an admin attests a root, which is a deployment event, and re-reading
        # it for every claim would be a query per task for an answer that
        # almost never differs. A worker restart picks up a new root.
        if adapter is None:
            with self.sessions() as session:
                self.adapter.extra_mounts.update(shared_root_mounts(session))
        self.store = PosixArtifactStore(settings.artifact_root)
        self.budget = Budget(
            cpu_millicores=settings.worker_budget_cpu_millicores,
            memory_bytes=settings.worker_budget_memory_bytes,
            max_concurrent_tasks=settings.worker_max_concurrent_tasks,
        )
        self._draining = threading.Event()
        self._idle_seconds = 1.0

    # --- lifecycle ------------------------------------------------------

    def register(self) -> None:
        with self.sessions() as session:
            session.execute(
                text(
                    "INSERT INTO workers (id, hostname, version, status, capacity) "
                    "VALUES (:i, :h, :v, 'active', :c) "
                    "ON CONFLICT (id) DO UPDATE SET status = 'active', "
                    "  last_heartbeat_at = now()"
                ),
                {
                    "i": self.worker_id,
                    "h": socket.gethostname(),
                    "v": "0.1.0",
                    "c": self.settings.worker_max_concurrent_tasks,
                },
            )
            session.commit()
        logger.info("worker %s registered", self.worker_id)

    def deregister(self, status: str = WorkerStatus.STOPPED) -> None:
        with self.sessions() as session:
            session.execute(
                text("UPDATE workers SET status = :s WHERE id = :i"),
                {"s": status, "i": self.worker_id},
            )
            session.commit()

    def install_signal_handlers(self) -> None:
        """SIGTERM and SIGINT start a drain rather than killing the process.

        A day-long task must not be destroyed because a deployment happened.
        The worker stops claiming and exits once the task in hand finishes.
        """

        def drain(signum: int, _frame: FrameType | None) -> None:
            logger.info("signal %s received; draining", signum)
            self._draining.set()

        signal.signal(signal.SIGTERM, drain)
        signal.signal(signal.SIGINT, drain)

    def reconcile(self) -> None:
        with self.sessions() as session:
            stopped = reconcile_orphans(self.adapter, session)
            session.commit()
        if stopped:
            logger.warning("stopped %d orphaned container(s): %s", len(stopped), stopped)

    # --- the loop -------------------------------------------------------

    def run_forever(self, *, max_iterations: int | None = None) -> int:
        """Claim and execute until drained. Returns the number of tasks run.

        ``max_iterations`` exists so a test can run a bounded number of
        cycles; production passes nothing.
        """
        self.register()
        self.reconcile()
        completed = 0
        iterations = 0
        try:
            while not self._draining.is_set():
                if max_iterations is not None and iterations >= max_iterations:
                    break
                iterations += 1
                claimed = self.claim()
                if claimed is None:
                    self.idle()
                    continue
                self._idle_seconds = 1.0
                self.execute(claimed)
                completed += 1
        finally:
            self.deregister()
        return completed

    def claim(self) -> ClaimedTask | None:
        """Claim one task and commit, so the lease is visible immediately."""
        with self.sessions() as session:
            task_id = claim_next_task(
                session,
                worker_id=self.worker_id,
                budget=self.budget,
                lease_seconds=self.settings.task_lease_seconds,
            )
            if task_id is None:
                session.rollback()
                return None
            row = session.execute(
                text(
                    "SELECT t.run_id, t.task_key, t.stage_key, t.task_spec, "
                    "       t.attempt_count, t.cpu_request_millicores, "
                    "       t.memory_request_bytes, t.wall_time_limit_seconds "
                    "FROM run_tasks t WHERE t.id = :i"
                ),
                {"i": task_id},
            ).one()
            session.commit()
        return ClaimedTask(
            task_id=task_id,
            run_id=row.run_id,
            task_key=row.task_key,
            stage_key=row.stage_key,
            task_spec=row.task_spec,
            attempt=row.attempt_count,
            limits=ResourceLimits(
                cpu_millicores=row.cpu_request_millicores,
                memory_bytes=row.memory_request_bytes,
                wall_time_seconds=row.wall_time_limit_seconds,
            ),
        )

    def idle(self) -> None:
        """Back off when nothing is claimable.

        ``None`` from the claim query does not mean the queue is empty: far
        more often the next task does not fit the remaining budget. Backing
        off exponentially keeps a full system from spinning on a query that
        will keep saying no.
        """
        time.sleep(min(self._idle_seconds, 30.0))
        self._idle_seconds = min(self._idle_seconds * 2, 30.0)

    def execute(self, claimed: ClaimedTask) -> None:
        """Run one task, holding no transaction while the container runs."""
        workspace = create_workspace(self.settings.workspace_root, claimed.run_id)
        cancelled = threading.Event()

        with self.sessions() as session:
            keeper = LeaseKeeper(
                self.sessions,
                task_id=claimed.task_id,
                worker_id=self.worker_id,
                interval_seconds=self.settings.task_heartbeat_seconds,
                lease_seconds=self.settings.task_lease_seconds,
                on_cancel=cancelled,
                draining=self._draining,
            )
            watcher = _CancelWatcher(
                self.adapter, cancelled, self.settings.task_cancel_grace_seconds
            )
            try:
                with keeper:
                    watcher.start(str(claimed.task_id))
                    outcome = execute_task(
                        session,
                        task_id=claimed.task_id,
                        run_id=claimed.run_id,
                        task_spec=claimed.task_spec,
                        stage_key=claimed.stage_key,
                        task_key=claimed.task_key,
                        attempt=claimed.attempt,
                        workspace=workspace,
                        adapter=self.adapter,
                        limits=claimed.limits,
                        image_ref=self.adapter.image,
                        worker_id=self.worker_id,
                        store=self.store,
                        log_max_bytes=self.settings.task_log_max_bytes,
                        log_retention_days=self.settings.task_log_retention_days,
                    )
            finally:
                watcher.stop()

            if outcome.succeeded:
                release_ready_tasks(session, claimed.run_id)
            advance_run(session, claimed.run_id)
            session.commit()

        logger.info(
            "task %s finished: %s%s",
            claimed.task_key,
            outcome.status,
            f" ({outcome.reason})" if outcome.reason else "",
        )


class _CancelWatcher:
    """Stops the container when the lease keeper reports a cancellation."""

    def __init__(
        self, adapter: DockerAdapter, cancelled: threading.Event, grace_seconds: int
    ) -> None:
        self._adapter = adapter
        self._cancelled = cancelled
        self._grace = grace_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, task_id: str) -> None:
        def watch() -> None:
            while not self._stop.wait(1.0):
                if self._cancelled.is_set():
                    # The container is named after the task, so it can be
                    # stopped without waiting for the adapter to return.
                    for name in self._adapter.orphans():
                        if task_id in name:
                            self._adapter.stop(name, grace_seconds=self._grace)
                    return

        self._thread = threading.Thread(target=watch, name="cancel-watch", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)


def main() -> int:  # pragma: no cover - process entry point
    from sqlalchemy import create_engine

    from app.settings import load_settings

    configure_logging("worker")
    settings = load_settings()
    engine = create_engine(str(settings.database_url), pool_pre_ping=True)
    worker = Worker(engine, settings)
    worker.install_signal_handlers()
    Path(settings.workspace_root).mkdir(parents=True, exist_ok=True)
    Path(settings.artifact_root).mkdir(parents=True, exist_ok=True)
    completed = worker.run_forever()
    logger.info("worker exiting after %d task(s)", completed)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
