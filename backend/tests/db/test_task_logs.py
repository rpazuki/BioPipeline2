"""What a task printed, kept and read back.

The first question about a failed task is what it said before it stopped. It
was written to a file in a workspace nobody could reach, and retention deleted
it. Everything here is about that file surviving and being readable.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.application.artifacts import promote_log
from app.application.pipelines import create_revision
from app.application.runs import submit_run
from app.application.task_logs import attempts_for_task, read_log
from app.domain.task_contract import ResourceLimits
from app.infrastructure.artifacts import PosixArtifactStore
from app.infrastructure.workspace import create_workspace

pytestmark = pytest.mark.db

DOC = """
pipeline: __NAME__
defaults: {root: /d}
stages:
  - name: only
    steps:
      - {name: a, package: labUtils.x, method: run}
"""


@pytest.fixture
def user(db: Session) -> uuid.UUID:
    return db.execute(
        text(
            "INSERT INTO users (email, display_name, role) VALUES (:e, 'L', 'admin') RETURNING id"
        ),
        {"e": f"log-{uuid.uuid4().hex[:10]}@example.org"},
    ).scalar_one()


@pytest.fixture
def worker_id(db: Session) -> str:
    """A registered worker: an attempt carries a foreign key to one."""
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
def store(tmp_path) -> PosixArtifactStore:
    return PosixArtifactStore(tmp_path / "artifacts")


@pytest.fixture
def run(db: Session, user) -> tuple[uuid.UUID, uuid.UUID]:
    revision = create_revision(
        db, source_text=DOC.replace("__NAME__", f"lg_{uuid.uuid4().hex[:8]}"), owner_id=user
    )
    submitted = submit_run(
        db, pipeline_revision_id=revision.revision_id, requested_by=user, values={}
    )
    task_id = db.execute(
        text("SELECT id FROM run_tasks WHERE run_id = :r LIMIT 1"), {"r": submitted.run_id}
    ).scalar_one()
    return submitted.run_id, task_id


def hold(db: Session, task_id: uuid.UUID, worker_id: str, attempt: int = 1) -> None:
    """Put the task in this worker's hands, as a claim would.

    The executor's final write is a compare-and-set against `claimed_by` and
    `attempt_count`: a worker may only record a verdict for a task it still
    owns. A test that calls `execute_task` on an unclaimed task is asking the
    executor to do the thing it now refuses.
    """
    db.execute(
        text(
            "UPDATE run_tasks SET status = 'running', claimed_by = :w, attempt_count = :n, "
            "lease_expires_at = now() + interval '1 hour' WHERE id = :i"
        ),
        {"w": worker_id, "n": attempt, "i": task_id},
    )


def start_attempt(db: Session, task_id: uuid.UUID, number: int = 1) -> uuid.UUID:
    return db.execute(
        text(
            "INSERT INTO run_task_attempts (task_id, attempt_number, image_ref, status) "
            "VALUES (:t, :n, 'img:dev', 'running') RETURNING id"
        ),
        {"t": task_id, "n": number},
    ).scalar_one()


def finish_attempt(db: Session, attempt_id: uuid.UUID, status: str = "failed") -> None:
    db.execute(
        text("UPDATE run_task_attempts SET status = :s, finished_at = now() WHERE id = :i"),
        {"s": status, "i": attempt_id},
    )


# --- keeping it ------------------------------------------------------------


def test_a_log_is_kept_as_an_artifact(db, run, store, tmp_path):
    run_id, task_id = run
    attempt_id = start_attempt(db, task_id)
    workspace = create_workspace(tmp_path / "workspaces", run_id)
    log = workspace.logs / "attempt-1.log"
    log.write_text("reading plate_01\nTraceback: it went wrong\n")

    artifact_id = promote_log(
        db,
        run_id=run_id,
        task_id=task_id,
        attempt_id=attempt_id,
        task_key="only",
        attempt=1,
        log_path=log,
        store=store,
        max_bytes=1024,
        retention_days=365,
    )
    assert artifact_id is not None
    row = db.execute(
        text("SELECT kind, retention_class, expires_at, filename FROM artifacts WHERE id = :a"),
        {"a": artifact_id},
    ).one()
    assert row.kind == "task_log"
    # Logs outlive outputs: a failure is diagnosed long after the results it
    # did not produce were cleaned up.
    assert row.retention_class == "long_term"
    assert row.filename == "only-attempt-1.log"


def test_the_attempt_points_at_its_log(db, run, store, tmp_path):
    run_id, task_id = run
    attempt_id = start_attempt(db, task_id)
    workspace = create_workspace(tmp_path / "workspaces", run_id)
    (workspace.logs / "attempt-1.log").write_text("hello\n")
    artifact_id = promote_log(
        db,
        run_id=run_id,
        task_id=task_id,
        attempt_id=attempt_id,
        task_key="only",
        attempt=1,
        log_path=workspace.logs / "attempt-1.log",
        store=store,
        max_bytes=1024,
        retention_days=365,
    )
    stored = db.execute(
        text("SELECT log_artifact_id FROM run_task_attempts WHERE id = :i"), {"i": attempt_id}
    ).scalar_one()
    assert stored == artifact_id


def test_a_task_that_printed_nothing_gets_no_artifact(db, run, store, tmp_path):
    run_id, task_id = run
    attempt_id = start_attempt(db, task_id)
    workspace = create_workspace(tmp_path / "workspaces", run_id)
    (workspace.logs / "attempt-1.log").write_text("")
    assert (
        promote_log(
            db,
            run_id=run_id,
            task_id=task_id,
            attempt_id=attempt_id,
            task_key="only",
            attempt=1,
            log_path=workspace.logs / "attempt-1.log",
            store=store,
            max_bytes=1024,
            retention_days=365,
        )
        is None
    )


def test_a_huge_log_keeps_its_tail_not_its_head(db, run, store, tmp_path):
    """The stack trace is at the end, and so is whatever the tool said before
    it stopped."""
    run_id, task_id = run
    attempt_id = start_attempt(db, task_id)
    workspace = create_workspace(tmp_path / "workspaces", run_id)
    log = workspace.logs / "attempt-1.log"
    log.write_text("chatter\n" * 5000 + "FATAL: the thing that matters\n")

    artifact_id = promote_log(
        db,
        run_id=run_id,
        task_id=task_id,
        attempt_id=attempt_id,
        task_key="only",
        attempt=1,
        log_path=log,
        store=store,
        max_bytes=2048,
        retention_days=365,
    )
    key = db.execute(
        text("SELECT storage_key FROM artifacts WHERE id = :a"), {"a": artifact_id}
    ).scalar_one()
    kept = store.path_for(key).read_text()
    assert "FATAL: the thing that matters" in kept
    # And it says that it is not the whole thing, rather than looking complete.
    assert "the rest was discarded" in kept
    assert len(kept.encode()) < 3000


# --- reading it ------------------------------------------------------------


def read(db, run_id, task_id, store, tmp_path, **kwargs):
    return read_log(
        db,
        task_id=task_id,
        run_id=run_id,
        store=store,
        workspace_root=tmp_path / "workspaces",
        **kwargs,
    )


def test_a_finished_attempt_is_read_from_its_artifact(db, run, store, tmp_path):
    run_id, task_id = run
    attempt_id = start_attempt(db, task_id)
    workspace = create_workspace(tmp_path / "workspaces", run_id)
    (workspace.logs / "attempt-1.log").write_text("it went wrong\n")
    promote_log(
        db,
        run_id=run_id,
        task_id=task_id,
        attempt_id=attempt_id,
        task_key="only",
        attempt=1,
        log_path=workspace.logs / "attempt-1.log",
        store=store,
        max_bytes=1024,
        retention_days=365,
    )
    finish_attempt(db, attempt_id)

    view = read(db, run_id, task_id, store, tmp_path)
    assert view.text == "it went wrong\n"
    assert view.live is False
    assert view.artifact_id is not None


def test_a_running_attempt_is_read_from_the_workspace(db, run, store, tmp_path):
    """So a day-long task can be watched rather than only examined
    afterwards."""
    run_id, task_id = run
    start_attempt(db, task_id)
    workspace = create_workspace(tmp_path / "workspaces", run_id)
    (workspace.logs / "attempt-1.log").write_text("plate 1 of 12\n")

    view = read(db, run_id, task_id, store, tmp_path)
    assert view.text == "plate 1 of 12\n"
    assert view.live is True
    assert view.artifact_id is None

    # And the same request later returns more, which is what `live` promises.
    (workspace.logs / "attempt-1.log").write_text("plate 1 of 12\nplate 2 of 12\n")
    assert "plate 2 of 12" in read(db, run_id, task_id, store, tmp_path).text


def test_only_the_tail_is_returned_and_it_says_so(db, run, store, tmp_path):
    run_id, task_id = run
    start_attempt(db, task_id)
    workspace = create_workspace(tmp_path / "workspaces", run_id)
    (workspace.logs / "attempt-1.log").write_text("x" * 100_000 + "END")

    view = read(db, run_id, task_id, store, tmp_path, tail_bytes=1024)
    assert view.truncated is True
    assert view.bytes_read == 1024
    assert view.bytes_total == 100_003
    assert view.text.endswith("END")


def test_the_latest_attempt_is_the_default_and_an_earlier_one_can_be_asked_for(
    db, run, store, tmp_path
):
    """A retry produces a second log, and the first one is still the evidence
    for why there was a retry."""
    run_id, task_id = run
    workspace = create_workspace(tmp_path / "workspaces", run_id)
    for number, body in ((1, "first attempt\n"), (2, "second attempt\n")):
        start_attempt(db, task_id, number)
        (workspace.logs / f"attempt-{number}.log").write_text(body)

    assert read(db, run_id, task_id, store, tmp_path).text == "second attempt\n"
    assert read(db, run_id, task_id, store, tmp_path, attempt_number=1).text == "first attempt\n"
    assert [a.attempt_number for a in attempts_for_task(db, task_id)] == [2, 1]


def test_a_task_never_attempted_has_no_log_at_all(db, run, store, tmp_path):
    """Different from an attempt that printed nothing, and rendered
    differently."""
    run_id, task_id = run
    assert read(db, run_id, task_id, store, tmp_path) is None


def test_an_attempt_that_printed_nothing_says_so(db, run, store, tmp_path):
    run_id, task_id = run
    attempt_id = start_attempt(db, task_id)
    finish_attempt(db, attempt_id, status="succeeded")
    view = read(db, run_id, task_id, store, tmp_path)
    assert view.text == ""
    assert "produced no output" in view.message


def test_a_log_whose_retention_expired_says_so(db, run, store, tmp_path):
    run_id, task_id = run
    attempt_id = start_attempt(db, task_id)
    workspace = create_workspace(tmp_path / "workspaces", run_id)
    (workspace.logs / "attempt-1.log").write_text("gone\n")
    artifact_id = promote_log(
        db,
        run_id=run_id,
        task_id=task_id,
        attempt_id=attempt_id,
        task_key="only",
        attempt=1,
        log_path=workspace.logs / "attempt-1.log",
        store=store,
        max_bytes=1024,
        retention_days=365,
    )
    finish_attempt(db, attempt_id)
    db.execute(
        text("UPDATE artifacts SET purged_at = now(), deleted_at = now() WHERE id = :a"),
        {"a": artifact_id},
    )
    view = read(db, run_id, task_id, store, tmp_path)
    assert "retention expired" in view.message


# --- the executor keeps it, whatever happened ------------------------------


class FailingAdapter:
    """A container that prints and then exits badly.

    Stands in for Docker so the claim under test — that a *failed* task keeps
    its log — can be asserted on a machine with no container runtime. It is
    the failure path that matters: a failed task whose log is gone tells
    nobody anything.
    """

    image = "img:dev"

    def __init__(self, output: str) -> None:
        self.output = output

    def unmounted_inputs(self, _spec) -> list[str]:
        return []

    def run(self, _spec, _root, *, log_path=None, container_name=None, environment=None):
        from app.infrastructure.execution.docker import ExecutionOutcome

        if log_path is not None:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text(self.output)
        return ExecutionOutcome(
            exit_code=1,
            container_id=container_name,
            timed_out=False,
            cancelled=False,
            result=None,
            log_path=log_path,
        )


def test_a_failed_task_keeps_its_log(db, run, store, tmp_path, worker_id):
    from app.workers.executor import execute_task

    run_id, task_id = run
    spec = db.execute(
        text("SELECT task_spec, task_key, stage_key FROM run_tasks WHERE id = :i"),
        {"i": task_id},
    ).one()
    workspace = create_workspace(tmp_path / "workspaces", run_id)
    hold(db, task_id, worker_id)

    outcome = execute_task(
        db,
        task_id=task_id,
        run_id=run_id,
        task_spec=spec.task_spec,
        stage_key=spec.stage_key,
        task_key=spec.task_key,
        attempt=1,
        workspace=workspace,
        adapter=FailingAdapter("loading data\nTraceback: boom\n"),
        limits=ResourceLimits(cpu_millicores=1000, memory_bytes=1024**3, wall_time_seconds=60),
        image_ref="img:dev",
        worker_id=worker_id,
        store=store,
        log_max_bytes=1024,
        log_retention_days=365,
    )

    assert outcome.status == "failed"
    view = read(db, run_id, task_id, store, tmp_path)
    assert "Traceback: boom" in view.text
    assert view.artifact_id is not None
    assert view.live is False


def test_a_log_that_cannot_be_kept_does_not_fail_the_task(
    db, run, tmp_path, monkeypatch, worker_id
):
    """The opposite call from the read audit, and for a reason: losing a log is
    bad, and losing a run's recorded outcome because the log could not be
    stored is worse."""
    from app.workers import executor

    def explode(*_args, **_kwargs):
        raise OSError("the artifact volume is full")

    monkeypatch.setattr(executor, "promote_log", explode)

    run_id, task_id = run
    spec = db.execute(
        text("SELECT task_spec, task_key, stage_key FROM run_tasks WHERE id = :i"),
        {"i": task_id},
    ).one()
    hold(db, task_id, worker_id)
    outcome = executor.execute_task(
        db,
        task_id=task_id,
        run_id=run_id,
        task_spec=spec.task_spec,
        stage_key=spec.stage_key,
        task_key=spec.task_key,
        attempt=1,
        workspace=create_workspace(tmp_path / "workspaces", run_id),
        adapter=FailingAdapter("something\n"),
        limits=ResourceLimits(cpu_millicores=1000, memory_bytes=1024**3, wall_time_seconds=60),
        image_ref="img:dev",
        worker_id=worker_id,
        store=PosixArtifactStore(tmp_path / "artifacts"),
    )
    # The outcome is still recorded, which is the whole point.
    assert outcome.status == "failed"
    assert (
        db.execute(text("SELECT status FROM run_tasks WHERE id = :i"), {"i": task_id}).scalar_one()
        == "failed"
    )
