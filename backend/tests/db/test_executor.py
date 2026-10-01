"""Who may record what happened to a task.

Two rules, both about a worker that is no longer the one it thinks it is:

* **A container the worker stopped is not a container that failed.** A
  cancellation recorded as a failure tells a researcher their science broke
  when they asked for it to stop, and poisons every failure count built on
  top of it.
* **A verdict is only valid from the owner.** A worker whose lease expired
  while its container was finishing must write nothing about the task: the
  reaper has requeued it and somebody else may already be running it.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.application.pipelines import create_revision
from app.application.runs import submit_run
from app.domain.task_contract import ResourceLimits
from app.infrastructure.artifacts import PosixArtifactStore
from app.infrastructure.execution.docker import ExecutionOutcome
from app.infrastructure.workspace import create_workspace
from app.workers.executor import execute_task
from app.workers.stopping import CANCELLED, LEASE_LOST, StopSignal

pytestmark = pytest.mark.db

DOC = """
pipeline: __NAME__
defaults: {root: /d}
stages:
  - name: only
    steps:
      - {name: a, package: labUtils.x, method: run}
"""

PRODUCING = """
pipeline: __NAME__
defaults: {root: /d}
stages:
  - name: only
    steps:
      - {name: a, package: labUtils.x, method: run}
    outputs:
      report: {path: "outputs/report.txt"}
"""


class StoppedAdapter:
    """A container that was killed from outside.

    Exactly what Docker reports for a cancellation, for a lost lease, and for
    an ordinary crash: a non-zero exit. The three are distinguishable only by
    what the *worker* knows, which is the point of the stop signal.
    """

    image = "img:dev"

    def __init__(self, exit_code: int = 137) -> None:
        self.exit_code = exit_code

    def unmounted_inputs(self, _spec) -> list[str]:
        return []

    def run(self, _spec, _root, *, log_path=None, container_name=None, environment=None):
        if log_path is not None:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text("working\n")
        return ExecutionOutcome(
            exit_code=self.exit_code,
            container_id=container_name,
            timed_out=False,
            # The adapter cannot know: from Docker's side a cancelled
            # container and a crashed one are both a non-zero exit.
            cancelled=False,
            result=None,
            log_path=log_path,
        )


@pytest.fixture
def user(db: Session) -> uuid.UUID:
    return db.execute(
        text(
            "INSERT INTO users (email, display_name, role) VALUES (:e, 'X', 'admin') RETURNING id"
        ),
        {"e": f"x-{uuid.uuid4().hex[:10]}@example.org"},
    ).scalar_one()


@pytest.fixture
def worker_id(db: Session) -> str:
    identifier = f"w-{uuid.uuid4().hex[:8]}"
    db.execute(
        text(
            "INSERT INTO workers (id, hostname, version, status) "
            "VALUES (:w, 'h', '0.1.0', 'active')"
        ),
        {"w": identifier},
    )
    return identifier


@pytest.fixture
def held(db: Session, user, worker_id) -> tuple[uuid.UUID, uuid.UUID]:
    """A run whose single task this worker holds, as a claim leaves it."""
    revision = create_revision(
        db, source_text=DOC.replace("__NAME__", f"ex_{uuid.uuid4().hex[:8]}"), owner_id=user
    )
    submitted = submit_run(
        db, pipeline_revision_id=revision.revision_id, requested_by=user, values={}
    )
    task_id = db.execute(
        text("SELECT id FROM run_tasks WHERE run_id = :r LIMIT 1"), {"r": submitted.run_id}
    ).scalar_one()
    db.execute(
        text(
            "UPDATE run_tasks SET status = 'running', claimed_by = :w, attempt_count = 1, "
            "lease_expires_at = now() + interval '1 hour' WHERE id = :i"
        ),
        {"w": worker_id, "i": task_id},
    )
    return submitted.run_id, task_id


def run_task(db: Session, held, worker_id, tmp_path, *, stop=None, attempt: int = 1):
    run_id, task_id = held
    spec = db.execute(
        text("SELECT task_spec, task_key, stage_key FROM run_tasks WHERE id = :i"),
        {"i": task_id},
    ).one()
    return execute_task(
        db,
        task_id=task_id,
        run_id=run_id,
        task_spec=spec.task_spec,
        stage_key=spec.stage_key,
        task_key=spec.task_key,
        attempt=attempt,
        workspace=create_workspace(tmp_path / "workspaces", run_id),
        adapter=StoppedAdapter(),
        limits=ResourceLimits(cpu_millicores=1000, memory_bytes=1024**3, wall_time_seconds=60),
        image_ref="img:dev",
        worker_id=worker_id,
        stop=stop,
    )


def task_row(db: Session, task_id: uuid.UUID):
    return db.execute(
        text("SELECT status, status_reason, claimed_by FROM run_tasks WHERE id = :i"),
        {"i": task_id},
    ).one()


def attempts(db: Session, task_id: uuid.UUID) -> list[str]:
    return [
        row[0]
        for row in db.execute(
            text("SELECT status FROM run_task_attempts WHERE task_id = :i ORDER BY attempt_number"),
            {"i": task_id},
        ).all()
    ]


# --- cancellation ----------------------------------------------------------


def test_a_cancelled_container_is_recorded_as_cancelled(db: Session, held, worker_id, tmp_path):
    """Not failed. The user asked for it to stop and it stopped."""
    _run_id, task_id = held
    stop = StopSignal()
    stop.raise_signal(CANCELLED)

    outcome = run_task(db, held, worker_id, tmp_path, stop=stop)

    assert outcome.status == "cancelled"
    assert outcome.attempt_status == "cancelled"
    assert task_row(db, task_id).status == "cancelled"
    assert attempts(db, task_id) == ["cancelled"]


def test_a_container_that_finished_first_keeps_its_success(
    db: Session, producing, worker_id, tmp_path
):
    """The precedence rule: a cancellation that arrives after the container
    has already produced its outputs does not throw them away. Cancelling the
    run still stops everything that had not started."""
    _run_id, task_id = producing
    stop = StopSignal()
    stop.raise_signal(CANCELLED)

    outcome = execute_producing(
        db,
        producing,
        worker_id,
        tmp_path,
        PosixArtifactStore(tmp_path / "artifacts"),
        ProducingAdapter(),
        stop=stop,
    )

    assert outcome.status == "succeeded"
    assert task_row(db, task_id).status == "succeeded"


def test_a_container_that_merely_failed_is_still_a_failure(db: Session, held, worker_id, tmp_path):
    """The other half of the rule: nothing here turns a crash into a
    cancellation just because the exit code looks the same."""
    _run_id, task_id = held

    outcome = run_task(db, held, worker_id, tmp_path, stop=StopSignal())

    assert outcome.status == "failed"
    assert task_row(db, task_id).status == "failed"


# --- ownership -------------------------------------------------------------


def test_a_worker_that_lost_its_lease_says_nothing_about_the_task(
    db: Session, held, worker_id, tmp_path
):
    """The reaper requeued it and another worker may be running it already."""
    _run_id, task_id = held
    db.execute(
        text(
            "UPDATE run_tasks SET status = 'queued', claimed_by = NULL, "
            "lease_expires_at = NULL WHERE id = :i"
        ),
        {"i": task_id},
    )
    stop = StopSignal()
    stop.raise_signal(LEASE_LOST)

    outcome = run_task(db, held, worker_id, tmp_path, stop=stop)

    assert outcome.owned is False
    assert not outcome.succeeded
    # The task is exactly as the reaper left it.
    row = task_row(db, task_id)
    assert row.status == "queued"
    assert row.status_reason is None
    # The attempt is this worker's own record and is closed honestly.
    assert attempts(db, task_id) == ["lost"]


def test_a_verdict_cannot_land_on_a_task_another_worker_now_holds(
    db: Session, held, worker_id, tmp_path
):
    """The race the compare-and-set exists for: the lease expired, the reaper
    requeued the task, a second worker claimed it, and only then did the first
    worker's container return."""
    _run_id, task_id = held
    successor = f"w-{uuid.uuid4().hex[:8]}"
    db.execute(
        text(
            "INSERT INTO workers (id, hostname, version, status) "
            "VALUES (:w, 'h', '0.1.0', 'active')"
        ),
        {"w": successor},
    )
    db.execute(
        text(
            "UPDATE run_tasks SET claimed_by = :w, attempt_count = 2, status = 'running', "
            "lease_expires_at = now() + interval '1 hour' WHERE id = :i"
        ),
        {"w": successor, "i": task_id},
    )

    outcome = run_task(db, held, worker_id, tmp_path, stop=StopSignal(), attempt=1)

    assert outcome.owned is False
    row = task_row(db, task_id)
    assert row.claimed_by == successor, "the old worker cleared the new owner's lease"
    assert row.status == "running"


def test_the_owner_can_still_record_its_own_verdict(db: Session, held, worker_id, tmp_path):
    """The guard must not refuse the ordinary case."""
    _run_id, task_id = held

    outcome = run_task(db, held, worker_id, tmp_path, stop=StopSignal())

    assert outcome.owned is True
    assert task_row(db, task_id).claimed_by is None


# --- the window between the container returning and the outputs being kept ---


class ProducingAdapter:
    """A container that succeeds and leaves the file it declared.

    `on_return` runs after the container has 'finished' and before the
    executor collects anything -- which is the window evaluation 2 found:
    output collection, promotion and delivery planning all happened before
    anybody asked whether the task was still this worker's.
    """

    image = "img:dev"

    def __init__(self, on_return=None) -> None:
        self.on_return = on_return

    def unmounted_inputs(self, _spec) -> list[str]:
        return []

    def run(self, _spec, root, *, log_path=None, container_name=None, environment=None):
        (root / "outputs").mkdir(parents=True, exist_ok=True)
        (root / "outputs" / "report.txt").write_text("mu_max 0.35\n")
        if log_path is not None:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text("done\n")
        if self.on_return is not None:
            self.on_return()
        return ExecutionOutcome(
            exit_code=0,
            container_id=container_name,
            timed_out=False,
            cancelled=False,
            result={"status": "succeeded", "outputs": {"report": "outputs/report.txt"}},
            log_path=log_path,
        )


@pytest.fixture
def producing(db: Session, user, worker_id) -> tuple[uuid.UUID, uuid.UUID]:
    revision = create_revision(
        db, source_text=PRODUCING.replace("__NAME__", f"ex_{uuid.uuid4().hex[:8]}"), owner_id=user
    )
    submitted = submit_run(
        db, pipeline_revision_id=revision.revision_id, requested_by=user, values={}
    )
    task_id = db.execute(
        text("SELECT id FROM run_tasks WHERE run_id = :r LIMIT 1"), {"r": submitted.run_id}
    ).scalar_one()
    db.execute(
        text(
            "UPDATE run_tasks SET status = 'running', claimed_by = :w, attempt_count = 1, "
            "lease_expires_at = now() + interval '1 hour' WHERE id = :i"
        ),
        {"w": worker_id, "i": task_id},
    )
    return submitted.run_id, task_id


def reclaim(db: Session, task_id: uuid.UUID, successor: str, *, attempt: int = 2) -> None:
    """What the reaper and the next worker do between the two: take it away."""
    db.execute(
        text(
            "INSERT INTO workers (id, hostname, version, status) "
            "VALUES (:w, 'h', '0.1.0', 'active') ON CONFLICT (id) DO NOTHING"
        ),
        {"w": successor},
    )
    db.execute(
        text(
            "UPDATE run_tasks SET claimed_by = :w, attempt_count = :n, status = 'running', "
            "lease_expires_at = now() + interval '1 hour' WHERE id = :i"
        ),
        {"w": successor, "n": attempt, "i": task_id},
    )


def artifacts_of(db: Session, run_id: uuid.UUID, kind: str = "task_output") -> int:
    return int(
        db.execute(
            text("SELECT count(*) FROM artifacts WHERE run_id = :r AND kind = :k"),
            {"r": run_id, "k": kind},
        ).scalar_one()
    )


def execute_producing(
    db, producing, worker_id, tmp_path, store, adapter, attempt: int = 1, stop=None
):
    run_id, task_id = producing
    spec = db.execute(
        text("SELECT task_spec, task_key, stage_key FROM run_tasks WHERE id = :i"),
        {"i": task_id},
    ).one()
    return execute_task(
        db,
        task_id=task_id,
        run_id=run_id,
        task_spec=spec.task_spec,
        stage_key=spec.stage_key,
        task_key=spec.task_key,
        attempt=attempt,
        workspace=create_workspace(tmp_path / "workspaces", run_id),
        adapter=adapter,
        limits=ResourceLimits(cpu_millicores=1000, memory_bytes=1024**3, wall_time_seconds=60),
        image_ref="img:dev",
        worker_id=worker_id,
        stop=stop,
        store=store,
    )


def test_a_task_taken_away_mid_flight_leaves_no_artifacts(
    db: Session, producing, worker_id, tmp_path
):
    """E2-01. The container succeeded; by the time its outputs were about to
    be kept, the task belonged to somebody else. Outputs promoted anyway would
    be downloadable results from an attempt that lost."""
    run_id, task_id = producing
    successor = f"w-{uuid.uuid4().hex[:8]}"
    store = PosixArtifactStore(tmp_path / "artifacts")

    outcome = execute_producing(
        db,
        producing,
        worker_id,
        tmp_path,
        store,
        ProducingAdapter(on_return=lambda: reclaim(db, task_id, successor)),
    )

    assert outcome.owned is False
    assert artifacts_of(db, run_id) == 0, "a losing attempt promoted its outputs"
    assert (
        db.execute(
            text("SELECT count(*) FROM run_deliveries WHERE run_id = :r"), {"r": run_id}
        ).scalar_one()
        == 0
    ), "a losing attempt planned delivery of its outputs"
    row = task_row(db, task_id)
    assert row.claimed_by == successor
    assert row.status == "running"


def test_the_owner_still_promotes_normally(db: Session, producing, worker_id, tmp_path):
    """The gate must not block the ordinary path it sits in front of."""
    run_id, task_id = producing
    store = PosixArtifactStore(tmp_path / "artifacts")

    outcome = execute_producing(db, producing, worker_id, tmp_path, store, ProducingAdapter())

    assert outcome.owned is True
    assert outcome.status == "succeeded"
    assert artifacts_of(db, run_id) == 1
    assert task_row(db, task_id).status == "succeeded"


def test_a_lost_attempt_keeps_the_reapers_account_of_it(
    db: Session, producing, worker_id, tmp_path
):
    """E2-02. The reaper recorded that this attempt was lost. A worker
    returning afterwards does not get to say it succeeded."""
    run_id, task_id = producing
    successor = f"w-{uuid.uuid4().hex[:8]}"
    store = PosixArtifactStore(tmp_path / "artifacts")

    def reclaimed_and_closed() -> None:
        reclaim(db, task_id, successor)
        # Exactly what `close_lost_attempts` does.
        db.execute(
            text(
                "UPDATE run_task_attempts SET status = 'lost', finished_at = now() "
                "WHERE task_id = :t AND status = 'running'"
            ),
            {"t": task_id},
        )

    outcome = execute_producing(
        db, producing, worker_id, tmp_path, store, ProducingAdapter(on_return=reclaimed_and_closed)
    )

    assert outcome.owned is False
    assert attempts(db, task_id) == ["lost"]
    # And the reaper's account is the one that survives: no result written
    # over it by the attempt that came back late.
    result = db.execute(
        text("SELECT result FROM run_task_attempts WHERE task_id = :t"), {"t": task_id}
    ).scalar_one()
    assert not (result or {}).get("outputs")
    assert artifacts_of(db, run_id) == 0
