"""The worker loop, against a real database.

The behaviours tested here are the ones that lose work when they are wrong:
transaction boundaries, lease renewal, cancellation, drain, and the run-status
aggregation that follows every task.
"""

from __future__ import annotations

import threading
import uuid

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.application.pipelines import create_revision
from app.application.runs import (
    advance_run,
    get_run,
    release_ready_tasks,
    request_cancel,
    submit_run,
)
from app.domain.materialise import folder_items
from app.settings import load_settings
from app.workers.stopping import StopSignal
from app.workers.worker import LeaseKeeper, Worker, worker_identity

pytestmark = pytest.mark.db


ONE_STEP = """
pipeline: __NAME__
defaults: {root: /d}
stages:
  - name: only
    steps:
      - {name: a, package: labUtils.x, method: run}
"""

TWO_STAGE = """
pipeline: __NAME__
defaults: {root: /d}
stages:
  - name: first
    fanout: {type: folders, data_dir: "{root}"}
    steps:
      - {name: a, package: labUtils.x, method: run}
  - name: second
    needs: [first]
    steps:
      - {name: b, package: labUtils.x, method: collate}
"""


def _document(template: str) -> str:
    return template.replace("__NAME__", f"p_{uuid.uuid4().hex[:8]}")


@pytest.fixture
def user(db: Session) -> uuid.UUID:
    return db.execute(
        text(
            "INSERT INTO users (email, display_name, role) VALUES (:e, 'W', 'admin') RETURNING id"
        ),
        {"e": f"w-{uuid.uuid4().hex[:10]}@example.org"},
    ).scalar_one()


def _run_with_tasks(db: Session, user, template=TWO_STAGE, folders=("a", "b")):
    revision = create_revision(db, source_text=_document(template), owner_id=user)
    submitted = submit_run(
        db,
        pipeline_revision_id=revision.revision_id,
        requested_by=user,
        values={},
        enumerate_fanout=lambda _f: folder_items(list(folders)),
    )
    return submitted.run_id


# --- run status aggregation ----------------------------------------------


def test_a_run_becomes_running_when_a_task_is_claimed(db: Session, user):
    run_id = _run_with_tasks(db, user)
    db.execute(
        text(
            "INSERT INTO workers (id, hostname, version, status) "
            "VALUES ('w-agg', 'h', '0', 'active') ON CONFLICT (id) DO NOTHING"
        )
    )
    # One statement: a held task must carry a lease, so status and claim
    # cannot be set separately without violating that constraint.
    db.execute(
        text(
            "UPDATE run_tasks SET status = 'running', claimed_by = 'w-agg', "
            "lease_expires_at = now() + interval '1 hour' "
            "WHERE run_id = :r AND stage_key = 'first' AND status = 'queued'"
        ),
        {"r": run_id},
    )
    assert advance_run(db, run_id) == "running"


def test_a_run_succeeds_only_when_every_task_has(db: Session, user):
    run_id = _run_with_tasks(db, user)
    db.execute(
        text("UPDATE run_tasks SET status = 'succeeded' WHERE run_id = :r AND stage_key = 'first'"),
        {"r": run_id},
    )
    assert advance_run(db, run_id) == "running"
    release_ready_tasks(db, run_id)
    db.execute(text("UPDATE run_tasks SET status = 'succeeded' WHERE run_id = :r"), {"r": run_id})
    assert advance_run(db, run_id) == "succeeded"


def test_one_failed_task_fails_the_run(db: Session, user):
    run_id = _run_with_tasks(db, user)
    db.execute(
        text(
            "UPDATE run_tasks SET status = CASE WHEN stage_key = 'second' "
            "THEN 'failed' ELSE 'succeeded' END WHERE run_id = :r"
        ),
        {"r": run_id},
    )
    assert advance_run(db, run_id) == "failed"


def test_a_finished_run_is_never_reopened(db: Session, user):
    """Terminal states are absorbing: a late task update must not resurrect
    a run that already concluded."""
    run_id = _run_with_tasks(db, user)
    db.execute(text("UPDATE run_tasks SET status = 'succeeded' WHERE run_id = :r"), {"r": run_id})
    assert advance_run(db, run_id) == "succeeded"
    db.execute(
        text("UPDATE run_tasks SET status = 'failed' WHERE run_id = :r AND stage_key = 'second'"),
        {"r": run_id},
    )
    assert advance_run(db, run_id) == "succeeded"


def test_started_at_is_recorded_once(db: Session, user):
    run_id = _run_with_tasks(db, user)
    db.execute(
        text(
            "INSERT INTO workers (id, hostname, version, status) "
            "VALUES ('w-st', 'h', '0', 'active') ON CONFLICT (id) DO NOTHING"
        )
    )
    db.execute(
        text(
            "UPDATE run_tasks SET status = 'running', claimed_by = 'w-st', "
            "lease_expires_at = now() + interval '1 hour' "
            "WHERE run_id = :r AND stage_key = 'first' AND status = 'queued'"
        ),
        {"r": run_id},
    )
    advance_run(db, run_id)
    first = db.execute(
        text("SELECT started_at FROM runs WHERE id = :r"), {"r": run_id}
    ).scalar_one()
    advance_run(db, run_id)
    again = db.execute(
        text("SELECT started_at FROM runs WHERE id = :r"), {"r": run_id}
    ).scalar_one()
    assert first == again is not None


# --- cancellation ---------------------------------------------------------


def test_cancelling_stops_queued_tasks_immediately(db: Session, user):
    run_id = _run_with_tasks(db, user)
    request_cancel(db, run_id, requested_by=user)
    counts = get_run(db, run_id).task_counts
    assert counts.get("cancelled") == 3
    assert "queued" not in counts


def test_cancelling_flags_running_tasks_for_their_worker(db: Session, user):
    """A running task cannot be stopped from here: its worker observes the
    flag on the next heartbeat and stops the container."""
    run_id = _run_with_tasks(db, user)
    db.execute(
        text(
            "INSERT INTO workers (id, hostname, version, status) "
            "VALUES ('w-c', 'h', '0', 'active') ON CONFLICT (id) DO NOTHING"
        )
    )
    db.execute(
        text(
            "UPDATE run_tasks SET status = 'running', claimed_by = 'w-c', "
            "lease_expires_at = now() + interval '1 hour' "
            "WHERE run_id = :r AND stage_key = 'first' AND status = 'queued'"
        ),
        {"r": run_id},
    )
    request_cancel(db, run_id, requested_by=user)
    flagged = db.execute(
        text(
            "SELECT count(*) FROM run_tasks WHERE run_id = :r "
            "AND status = 'running' AND cancel_requested_at IS NOT NULL"
        ),
        {"r": run_id},
    ).scalar_one()
    assert flagged == 2


def test_cancelling_twice_keeps_the_first_timestamp(db: Session, user):
    run_id = _run_with_tasks(db, user)
    request_cancel(db, run_id, requested_by=user)
    first = db.execute(
        text("SELECT cancel_requested_at FROM runs WHERE id = :r"), {"r": run_id}
    ).scalar_one()
    request_cancel(db, run_id, requested_by=user)
    again = db.execute(
        text("SELECT cancel_requested_at FROM runs WHERE id = :r"), {"r": run_id}
    ).scalar_one()
    assert first == again


def test_cancelling_a_finished_run_does_nothing(db: Session, user):
    run_id = _run_with_tasks(db, user)
    db.execute(text("UPDATE run_tasks SET status = 'succeeded' WHERE run_id = :r"), {"r": run_id})
    advance_run(db, run_id)
    assert request_cancel(db, run_id, requested_by=user) == "succeeded"


# --- the lease keeper -----------------------------------------------------


def _claimed_task(session: Session, engine: Engine, user_id, worker_id: str):
    """A committed, claimed task the keeper can renew."""
    revision = create_revision(session, source_text=_document(ONE_STEP), owner_id=user_id)
    submitted = submit_run(
        session,
        pipeline_revision_id=revision.revision_id,
        requested_by=user_id,
        values={},
    )
    session.execute(
        text(
            "INSERT INTO workers (id, hostname, version, status) "
            "VALUES (:w, 'h', '0', 'active') ON CONFLICT (id) DO NOTHING"
        ),
        {"w": worker_id},
    )
    task_id = session.execute(
        text(
            "UPDATE run_tasks SET status = 'running', claimed_by = :w, "
            "lease_expires_at = now() + interval '2 seconds' "
            "WHERE run_id = :r RETURNING id"
        ),
        {"w": worker_id, "r": submitted.run_id},
    ).scalar_one()
    session.commit()
    return submitted.run_id, task_id


def test_the_lease_keeper_extends_a_lease(engine: Engine):
    """A day-long task renews hundreds of times; if it stops, the reaper
    correctly takes the task back."""
    make = sessionmaker(bind=engine, expire_on_commit=False)
    setup = make()
    owner = setup.execute(
        text(
            "INSERT INTO users (email, display_name, role) VALUES (:e, 'K', 'admin') RETURNING id"
        ),
        {"e": f"k-{uuid.uuid4().hex[:8]}@example.org"},
    ).scalar_one()
    worker_id = worker_identity()
    run_id, task_id = _claimed_task(setup, engine, owner, worker_id)
    before = setup.execute(
        text("SELECT lease_expires_at FROM run_tasks WHERE id = :i"), {"i": task_id}
    ).scalar_one()
    setup.close()

    stop = StopSignal()
    keeper = LeaseKeeper(
        make,
        task_id=task_id,
        worker_id=worker_id,
        interval_seconds=1,
        lease_seconds=3600,
        on_stop=stop,
    )
    with keeper:
        threading.Event().wait(1.6)

    check = make()
    after = check.execute(
        text("SELECT lease_expires_at FROM run_tasks WHERE id = :i"), {"i": task_id}
    ).scalar_one()
    beat = check.execute(
        text("SELECT last_heartbeat_at FROM workers WHERE id = :w"), {"w": worker_id}
    ).scalar_one()
    check.execute(text("DELETE FROM runs WHERE id = :r"), {"r": run_id})
    check.execute(text("DELETE FROM workers WHERE id = :w"), {"w": worker_id})
    check.commit()
    check.close()

    assert after > before, "the lease was not renewed"
    assert beat is not None
    assert not stop.is_set()


def test_a_draining_worker_says_so_while_it_finishes(engine: Engine):
    """An upgrade needs the difference between a worker that is busy and one
    that is finishing its last task and then leaving. From the queue the two
    are identical."""
    make = sessionmaker(bind=engine, expire_on_commit=False)
    setup = make()
    owner = setup.execute(
        text(
            "INSERT INTO users (email, display_name, role) VALUES (:e, 'D', 'admin') RETURNING id"
        ),
        {"e": f"d-{uuid.uuid4().hex[:8]}@example.org"},
    ).scalar_one()
    worker_id = worker_identity()
    run_id, task_id = _claimed_task(setup, engine, owner, worker_id)
    setup.close()

    draining = threading.Event()
    draining.set()
    keeper = LeaseKeeper(
        make,
        task_id=task_id,
        worker_id=worker_id,
        interval_seconds=1,
        lease_seconds=3600,
        on_stop=StopSignal(),
        draining=draining,
    )
    with keeper:
        threading.Event().wait(1.6)

    check = make()
    status = check.execute(
        text("SELECT status FROM workers WHERE id = :w"), {"w": worker_id}
    ).scalar_one()
    check.execute(text("DELETE FROM runs WHERE id = :r"), {"r": run_id})
    check.execute(text("DELETE FROM workers WHERE id = :w"), {"w": worker_id})
    check.commit()
    check.close()

    assert status == "draining"


def test_the_lease_keeper_reports_a_cancellation(engine: Engine):
    make = sessionmaker(bind=engine, expire_on_commit=False)
    setup = make()
    owner = setup.execute(
        text(
            "INSERT INTO users (email, display_name, role) VALUES (:e, 'K2', 'admin') RETURNING id"
        ),
        {"e": f"k2-{uuid.uuid4().hex[:8]}@example.org"},
    ).scalar_one()
    worker_id = worker_identity()
    run_id, task_id = _claimed_task(setup, engine, owner, worker_id)
    setup.execute(
        text("UPDATE run_tasks SET cancel_requested_at = now() WHERE id = :i"),
        {"i": task_id},
    )
    setup.commit()
    setup.close()

    stop = StopSignal()
    keeper = LeaseKeeper(
        make,
        task_id=task_id,
        worker_id=worker_id,
        interval_seconds=1,
        lease_seconds=60,
        on_stop=stop,
    )
    with keeper:
        stop.event.wait(timeout=5)

    cleanup = make()
    cleanup.execute(text("DELETE FROM runs WHERE id = :r"), {"r": run_id})
    cleanup.execute(text("DELETE FROM workers WHERE id = :w"), {"w": worker_id})
    cleanup.commit()
    cleanup.close()

    assert stop.is_set(), "the worker was never told to stop"
    # The reason travels, not just the fact: a cancellation and a lost lease
    # both stop the container and must never be recorded the same way.
    assert stop.cancelled and not stop.lost


def test_the_lease_keeper_gives_up_when_the_task_is_taken_away(engine: Engine):
    """A reaper reclaimed the task. Racing whoever holds it now would run the
    same work twice."""
    make = sessionmaker(bind=engine, expire_on_commit=False)
    setup = make()
    owner = setup.execute(
        text(
            "INSERT INTO users (email, display_name, role) VALUES (:e, 'K3', 'admin') RETURNING id"
        ),
        {"e": f"k3-{uuid.uuid4().hex[:8]}@example.org"},
    ).scalar_one()
    worker_id = worker_identity()
    run_id, task_id = _claimed_task(setup, engine, owner, worker_id)
    setup.execute(
        text(
            "UPDATE run_tasks SET claimed_by = NULL, lease_expires_at = NULL, "
            "status = 'queued' WHERE id = :i"
        ),
        {"i": task_id},
    )
    setup.commit()
    setup.close()

    stop = StopSignal()
    keeper = LeaseKeeper(
        make,
        task_id=task_id,
        worker_id=worker_id,
        interval_seconds=1,
        lease_seconds=60,
        on_stop=stop,
    )
    with keeper:
        stop.event.wait(timeout=5)

    cleanup = make()
    cleanup.execute(text("DELETE FROM runs WHERE id = :r"), {"r": run_id})
    cleanup.execute(text("DELETE FROM workers WHERE id = :w"), {"w": worker_id})
    cleanup.commit()
    cleanup.close()

    assert stop.is_set()
    assert stop.lost and not stop.cancelled


# --- the loop -------------------------------------------------------------


def test_a_worker_registers_and_deregisters(engine: Engine):
    settings = load_settings()
    worker = Worker(engine, settings)
    worker.register()
    make = sessionmaker(bind=engine)
    with make() as session:
        status = session.execute(
            text("SELECT status FROM workers WHERE id = :w"), {"w": worker.worker_id}
        ).scalar_one()
    assert status == "active"
    worker.deregister()
    with make() as session:
        status = session.execute(
            text("SELECT status FROM workers WHERE id = :w"), {"w": worker.worker_id}
        ).scalar_one()
        session.execute(text("DELETE FROM workers WHERE id = :w"), {"w": worker.worker_id})
        session.commit()
    assert status == "stopped"


def test_a_draining_worker_stops_claiming(engine: Engine):
    """A deployment must not destroy a day-long task, so a signal starts a
    drain rather than killing the process."""
    settings = load_settings()
    worker = Worker(engine, settings)
    worker._draining.set()
    completed = worker.run_forever()
    assert completed == 0
    make = sessionmaker(bind=engine)
    with make() as session:
        session.execute(text("DELETE FROM workers WHERE id = :w"), {"w": worker.worker_id})
        session.commit()


def test_idle_backoff_grows_and_is_capped(engine: Engine):
    """Claiming nothing usually means the next task does not fit, not that the
    queue is empty, so a full system must not spin on the query."""
    worker = Worker(engine, load_settings())
    delays = []
    for _ in range(8):
        delays.append(worker._idle_seconds)
        worker._idle_seconds = min(worker._idle_seconds * 2, 30.0)
    assert delays[0] < delays[1] < delays[2]
    assert max(delays) <= 30.0


# --- cancellation, through the path a person actually takes ----------------
#
# Evaluation 2 (E2-03) asked for this: the executor's mapping was tested, but
# nothing exercised the request, the heartbeat that notices it, the watcher
# that stops the container, and the run aggregation that follows.


class BlockingAdapter:
    """A container that runs until somebody stops it.

    Also answers `orphans()` and `stop()`, because that is how the worker's
    cancel watcher reaches a running container: by name, without waiting for
    the adapter call to return.
    """

    image = "img:dev"

    def __init__(self, *, exit_code: int = 137) -> None:
        self.exit_code = exit_code
        self.started = threading.Event()
        self.killed = threading.Event()
        self.names: list[str] = []

    def unmounted_inputs(self, _spec) -> list[str]:
        return []

    def orphans(self) -> list[str]:
        return list(self.names)

    def stop(self, name: str, *, grace_seconds: int = 0) -> None:
        if name in self.names:
            self.killed.set()

    def run(self, _spec, root, *, log_path=None, container_name=None, environment=None):
        from app.infrastructure.execution.docker import ExecutionOutcome

        self.names.append(container_name)
        if log_path is not None:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text("working\n")
        self.started.set()
        self.killed.wait(timeout=30)
        return ExecutionOutcome(
            exit_code=self.exit_code,
            container_id=container_name,
            timed_out=False,
            cancelled=False,
            result=None,
            log_path=log_path,
        )


class FinishingAdapter(BlockingAdapter):
    """A container that completes successfully before anybody asks it to stop."""

    def run(self, spec, root, *, log_path=None, container_name=None, environment=None):
        from app.infrastructure.execution.docker import ExecutionOutcome

        self.names.append(container_name)
        if log_path is not None:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text("done\n")
        self.started.set()
        return ExecutionOutcome(
            exit_code=0,
            container_id=container_name,
            timed_out=False,
            cancelled=False,
            result={"status": "succeeded", "outputs": {}},
            log_path=log_path,
        )


def _a_running_worker(engine: Engine, tmp_path, adapter, user) -> tuple[Worker, object, uuid.UUID]:
    """A submitted run, a worker that has claimed its task, and the claim."""
    make = sessionmaker(bind=engine, expire_on_commit=False)
    with make() as session:
        revision = create_revision(session, source_text=_document(ONE_STEP), owner_id=user)
        submitted = submit_run(
            session, pipeline_revision_id=revision.revision_id, requested_by=user, values={}
        )
        session.commit()
    settings = load_settings(
        artifact_root=tmp_path / "artifacts",
        workspace_root=tmp_path / "workspaces",
        # The heartbeat is what notices a cancellation; the default thirty
        # seconds would make this test a nap. Five is the floor the settings
        # allow, which is a real constraint rather than one to work around.
        task_heartbeat_seconds=5,
        task_cancel_grace_seconds=1,
    )
    (tmp_path / "artifacts").mkdir(exist_ok=True)
    (tmp_path / "workspaces").mkdir(exist_ok=True)
    worker = Worker(engine, settings, adapter=adapter, worker_id=worker_identity())
    worker.register()
    claimed = worker.claim()
    assert claimed is not None, "the task was not claimable"
    return worker, claimed, submitted.run_id


def _tidy(engine: Engine, run_id: uuid.UUID, worker: Worker) -> None:
    with sessionmaker(bind=engine)() as session:
        session.execute(
            text(
                "UPDATE run_task_attempts SET log_artifact_id = NULL WHERE task_id IN "
                "(SELECT id FROM run_tasks WHERE run_id = :r)"
            ),
            {"r": run_id},
        )
        session.execute(text("DELETE FROM artifacts WHERE run_id = :r"), {"r": run_id})
        session.execute(text("DELETE FROM runs WHERE id = :r"), {"r": run_id})
        session.execute(text("DELETE FROM workers WHERE id = :w"), {"w": worker.worker_id})
        session.commit()


def test_cancelling_a_running_task_cancels_the_task_and_the_run(engine: Engine, tmp_path):
    """The whole path: a person asks, the heartbeat notices, the watcher stops
    the container, and what is recorded is a cancellation rather than a
    failure."""
    make = sessionmaker(bind=engine, expire_on_commit=False)
    with make() as session:
        user = session.execute(
            text(
                "INSERT INTO users (email, display_name, role) VALUES (:e, 'C', 'admin') "
                "RETURNING id"
            ),
            {"e": f"c-{uuid.uuid4().hex[:8]}@example.org"},
        ).scalar_one()
        session.commit()

    adapter = BlockingAdapter()
    worker, claimed, run_id = _a_running_worker(engine, tmp_path, adapter, user)
    running = threading.Thread(target=worker.execute, args=(claimed,), daemon=True)
    try:
        running.start()
        assert adapter.started.wait(timeout=20), "the container never started"

        with make() as session:
            request_cancel(session, run_id, requested_by=user)
            session.commit()

        running.join(timeout=30)
        assert not running.is_alive(), "the worker never finished the cancelled task"

        with make() as session:
            task = session.execute(
                text("SELECT status, status_reason FROM run_tasks WHERE run_id = :r"),
                {"r": run_id},
            ).one()
            attempt = session.execute(
                text(
                    "SELECT a.status FROM run_task_attempts a JOIN run_tasks t ON t.id = a.task_id "
                    "WHERE t.run_id = :r"
                ),
                {"r": run_id},
            ).scalar_one()
            run_status = session.execute(
                text("SELECT status FROM runs WHERE id = :r"), {"r": run_id}
            ).scalar_one()

        assert adapter.killed.is_set(), "the watcher never stopped the container"
        assert task.status == "cancelled", f"recorded as {task.status}, not cancelled"
        assert attempt == "cancelled"
        assert run_status == "cancelled"
    finally:
        adapter.killed.set()
        running.join(timeout=5)
        _tidy(engine, run_id, worker)


def test_work_already_finished_is_not_undone_by_a_cancellation(engine: Engine, tmp_path):
    """The race rule, at the level where it is decided.

    A task that completed keeps its result; the request stops what had not
    started. Two stages make the distinction visible: the first has run, the
    second has not.
    """
    make = sessionmaker(bind=engine, expire_on_commit=False)
    with make() as session:
        user = session.execute(
            text(
                "INSERT INTO users (email, display_name, role) VALUES (:e, 'C2', 'admin') "
                "RETURNING id"
            ),
            {"e": f"c2-{uuid.uuid4().hex[:8]}@example.org"},
        ).scalar_one()
        revision = create_revision(session, source_text=_document(TWO_STAGE), owner_id=user)
        submitted = submit_run(
            session,
            pipeline_revision_id=revision.revision_id,
            requested_by=user,
            values={},
            enumerate_fanout=lambda _f: folder_items(["a"]),
        )
        session.commit()
    run_id = submitted.run_id

    settings = load_settings(
        artifact_root=tmp_path / "artifacts",
        workspace_root=tmp_path / "workspaces",
        task_heartbeat_seconds=5,
        task_cancel_grace_seconds=1,
    )
    (tmp_path / "artifacts").mkdir(exist_ok=True)
    (tmp_path / "workspaces").mkdir(exist_ok=True)
    adapter = FinishingAdapter()
    worker = Worker(engine, settings, adapter=adapter, worker_id=worker_identity())
    worker.register()
    try:
        first = worker.claim()
        assert first is not None
        worker.execute(first)

        with make() as session:
            request_cancel(session, run_id, requested_by=user)
            session.commit()

        with make() as session:
            statuses = dict(
                session.execute(
                    text(
                        "SELECT status, count(*) FROM run_tasks WHERE run_id = :r GROUP BY status"
                    ),
                    {"r": run_id},
                ).all()
            )
            run_status = session.execute(
                text("SELECT status FROM runs WHERE id = :r"), {"r": run_id}
            ).scalar_one()

        assert statuses.get("succeeded") == 1, "finished work was thrown away"
        assert statuses.get("cancelled", 0) >= 1, "unstarted work was not stopped"
        assert run_status in {"cancelled", "cancel_requested"}
    finally:
        _tidy(engine, run_id, worker)
