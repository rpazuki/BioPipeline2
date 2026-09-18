"""The reaper: the process that makes failures converge.

Everything here is a way work gets lost when nobody is watching. Each test
creates the failure and asserts the system recovers from it.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.application.pipelines import create_revision
from app.application.runs import get_run, request_cancel, submit_run
from app.application.uploads import staging_key
from app.domain.materialise import folder_items
from app.infrastructure.artifacts import PosixArtifactStore
from app.settings import load_settings
from app.workers.reaper import (
    Reaper,
    close_lost_attempts,
    converge_cancellations,
    expire_uploads,
    expire_workspaces,
    purge_expired_artifacts,
    reap_dead_workers,
    reclaim_leases,
)

pytestmark = pytest.mark.db


ONE_STAGE = """
pipeline: __NAME__
defaults: {root: /d}
stages:
  - name: only
    fanout: {type: folders, data_dir: "{root}"}
    steps:
      - {name: a, package: labUtils.x, method: run}
"""


@pytest.fixture
def user(db: Session) -> uuid.UUID:
    return db.execute(
        text(
            "INSERT INTO users (email, display_name, role) VALUES (:e, 'R', 'admin') RETURNING id"
        ),
        {"e": f"r-{uuid.uuid4().hex[:10]}@example.org"},
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


def _run(db: Session, user, folders=("a", "b")) -> uuid.UUID:
    revision = create_revision(
        db,
        source_text=ONE_STAGE.replace("__NAME__", f"p_{uuid.uuid4().hex[:8]}"),
        owner_id=user,
    )
    return submit_run(
        db,
        pipeline_revision_id=revision.revision_id,
        requested_by=user,
        values={},
        enumerate_fanout=lambda _f: folder_items(list(folders)),
    ).run_id


def _hold(db: Session, run_id, worker_id, *, lease: str, attempts: int = 1) -> uuid.UUID:
    """Put one task in a worker's hands with a given lease expiry."""
    return db.execute(
        text(
            "UPDATE run_tasks SET status = 'running', claimed_by = :w, "
            "  lease_expires_at = now() + CAST(:lease AS interval), attempt_count = :n "
            "WHERE id = (SELECT id FROM run_tasks WHERE run_id = :r LIMIT 1) "
            "RETURNING id"
        ),
        {"w": worker_id, "lease": lease, "n": attempts, "r": run_id},
    ).scalar_one()


# --- expired leases -------------------------------------------------------


def test_an_expired_lease_returns_the_task_to_the_queue(db: Session, user, worker_id):
    """The worker that would release it is precisely the one that is gone."""
    run_id = _run(db, user)
    task_id = _hold(db, run_id, worker_id, lease="-1 minute")
    report = reclaim_leases(db, poison_limit=3)
    assert task_id in report.leases_requeued
    status = db.execute(
        text("SELECT status FROM run_tasks WHERE id = :i"), {"i": task_id}
    ).scalar_one()
    assert status == "queued"


def test_a_live_lease_is_left_alone(db: Session, user, worker_id):
    run_id = _run(db, user)
    _hold(db, run_id, worker_id, lease="1 hour")
    assert not reclaim_leases(db, poison_limit=3).changed


def test_a_task_that_keeps_losing_its_lease_eventually_fails(db: Session, user, worker_id):
    """Without a poison limit a task that never reports back cycles forever."""
    run_id = _run(db, user)
    task_id = _hold(db, run_id, worker_id, lease="-1 minute", attempts=9)
    report = reclaim_leases(db, poison_limit=3)
    assert task_id in report.leases_failed
    status = db.execute(
        text("SELECT status FROM run_tasks WHERE id = :i"), {"i": task_id}
    ).scalar_one()
    assert status == "failed"


def test_reclaiming_advances_the_run(db: Session, user, worker_id):
    """A reclaimed task changes the run's aggregate; without advancing it the
    change would be invisible."""
    run_id = _run(db, user, folders=("only",))
    _hold(db, run_id, worker_id, lease="-1 minute", attempts=9)
    reclaim_leases(db, poison_limit=3)
    assert get_run(db, run_id).status == "failed"


def test_one_poisoned_branch_does_not_abort_the_others(db: Session, user, worker_id):
    """Fan-out branches are independent work. A researcher wants the twelve
    results that succeeded, not zero because the thirteenth failed, so the run
    concludes only once every task is terminal."""
    run_id = _run(db, user, folders=("a", "b"))
    _hold(db, run_id, worker_id, lease="-1 minute", attempts=9)
    reclaim_leases(db, poison_limit=3)
    assert get_run(db, run_id).status == "running"

    db.execute(
        text("UPDATE run_tasks SET status = 'succeeded' WHERE run_id = :r AND status = 'queued'"),
        {"r": run_id},
    )
    from app.application.runs import advance_run

    assert advance_run(db, run_id) == "failed"


def test_a_lost_attempt_is_closed(db: Session, user, worker_id):
    """An attempt left running forever makes it look as though the work is
    still going when the worker is long gone."""
    run_id = _run(db, user)
    task_id = _hold(db, run_id, worker_id, lease="-1 minute")
    db.execute(
        text(
            "INSERT INTO run_task_attempts (task_id, attempt_number, image_ref, status) "
            "VALUES (:t, 1, 'img', 'running')"
        ),
        {"t": task_id},
    )
    reclaim_leases(db, poison_limit=3)
    assert close_lost_attempts(db) == 1
    status = db.execute(
        text("SELECT status FROM run_task_attempts WHERE task_id = :t"), {"t": task_id}
    ).scalar_one()
    assert status == "lost"


# --- cancellation convergence ---------------------------------------------


def test_a_cancelled_run_converges_once_its_tasks_stop(db: Session, user):
    """The worker holding the last task may have died between stopping the
    container and recording it, so the reaper owns this transition."""
    run_id = _run(db, user)
    request_cancel(db, run_id, requested_by=user)
    converged = converge_cancellations(db)
    assert run_id in converged
    assert get_run(db, run_id).status == "cancelled"


def test_a_cancelled_run_with_work_still_running_does_not_converge(db: Session, user, worker_id):
    run_id = _run(db, user)
    _hold(db, run_id, worker_id, lease="1 hour")
    request_cancel(db, run_id, requested_by=user)
    assert converge_cancellations(db) == []
    assert get_run(db, run_id).status == "cancel_requested"


def test_convergence_is_idempotent(db: Session, user):
    run_id = _run(db, user)
    request_cancel(db, run_id, requested_by=user)
    converge_cancellations(db)
    assert converge_cancellations(db) == []


# --- dead workers ---------------------------------------------------------


def test_a_worker_whose_heartbeat_stopped_is_reaped(db: Session, worker_id):
    db.execute(
        text("UPDATE workers SET last_heartbeat_at = now() - interval '2 hours' WHERE id = :w"),
        {"w": worker_id},
    )
    assert worker_id in reap_dead_workers(db, stale_seconds=600)
    status = db.execute(
        text("SELECT status FROM workers WHERE id = :w"), {"w": worker_id}
    ).scalar_one()
    assert status == "stopped"


def test_a_beating_worker_is_left_alone(db: Session, worker_id):
    assert worker_id not in reap_dead_workers(db, stale_seconds=600)


# --- retention ------------------------------------------------------------


@pytest.fixture
def store(tmp_path):
    return PosixArtifactStore(tmp_path / "artifacts")


def _artifact(db: Session, store, *, expires: str) -> tuple[uuid.UUID, str]:
    project = db.execute(text("SELECT id FROM projects WHERE is_default")).scalar_one()
    key = f"runs/{uuid.uuid4()}/out"
    path = store.path_for(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("bytes")
    artifact_id = db.execute(
        text(
            "INSERT INTO artifacts (project_id, kind, storage_key, filename, "
            " size_bytes, expires_at) "
            "VALUES (:p, 'task_output', :k, 'out', 5, now() + CAST(:e AS interval)) "
            "RETURNING id"
        ),
        {"p": project, "k": key, "e": expires},
    ).scalar_one()
    return artifact_id, key


def test_an_expired_artifact_has_its_bytes_deleted(db: Session, store):
    _artifact_id, key = _artifact(db, store, expires="-1 day")
    purged, missing = purge_expired_artifacts(db, store)
    assert (purged, missing) == (1, 0)
    assert not store.exists(key)


def test_purging_records_that_the_bytes_are_actually_gone(db: Session, store):
    """purged_at is what makes deletion verifiable rather than merely
    recorded, which is the distinction ADR 0012 rests on."""
    artifact_id, _ = _artifact(db, store, expires="-1 day")
    purge_expired_artifacts(db, store)
    row = db.execute(
        text("SELECT deleted_at, purged_at FROM artifacts WHERE id = :i"),
        {"i": artifact_id},
    ).one()
    assert row.deleted_at is not None and row.purged_at is not None


def test_an_unexpired_artifact_is_untouched(db: Session, store):
    _artifact(db, store, expires="30 days")
    assert purge_expired_artifacts(db, store) == (0, 0)


def test_bytes_already_gone_are_still_marked_purged(db: Session, store):
    """A previous sweep interrupted between the delete and the update. Marking
    it purged is still correct, and the count distinguishes the two cases."""
    artifact_id, key = _artifact(db, store, expires="-1 day")
    store.delete(key)
    purged, missing = purge_expired_artifacts(db, store)
    assert (purged, missing) == (0, 1)
    purged_at = db.execute(
        text("SELECT purged_at FROM artifacts WHERE id = :i"), {"i": artifact_id}
    ).scalar_one()
    assert purged_at is not None


def test_purging_is_idempotent(db: Session, store):
    _artifact(db, store, expires="-1 day")
    purge_expired_artifacts(db, store)
    assert purge_expired_artifacts(db, store) == (0, 0)


def test_an_expired_workspace_is_marked(db: Session, user):
    run_id = _run(db, user)
    db.execute(
        text(
            "INSERT INTO workspaces (run_id, root_key, quota_bytes, expires_at) "
            "VALUES (:r, 'k', 1000, now() - interval '1 day')"
        ),
        {"r": run_id},
    )
    assert expire_workspaces(db) == 1


def _abandoned_upload(db: Session, user, store, *, expires: str) -> uuid.UUID:
    """An upload with bytes on disk, as an interrupted transfer leaves one."""
    project = db.execute(text("SELECT id FROM projects WHERE is_default")).scalar_one()
    upload_id = db.execute(
        text(
            "INSERT INTO uploads (project_id, owner_id, filename, storage_key, "
            " received_bytes, expires_at) VALUES (:p, :u, 'big.bam', :k, 9, "
            f" now() {expires}) RETURNING id"
        ),
        {"p": project, "u": user, "k": "pending"},
    ).scalar_one()
    path = store.path_for(staging_key(upload_id))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"half a bam")
    db.execute(
        text("UPDATE uploads SET storage_key = :k WHERE id = :i"),
        {"k": staging_key(upload_id), "i": upload_id},
    )
    return upload_id


def test_an_abandoned_upload_is_expired(db: Session, user, store):
    """A chunked upload started and never finished holds disk and a storage
    key indefinitely; with multi-gigabyte inputs that is real space."""
    upload_id = _abandoned_upload(db, user, store, expires="- interval '1 hour'")

    assert expire_uploads(db, store) == 1
    # The row alone would be the version of this that looks finished and
    # reclaims nothing.
    assert not store.exists(staging_key(upload_id))


def test_a_live_upload_is_left_alone(db: Session, user, store):
    upload_id = _abandoned_upload(db, user, store, expires="+ interval '1 day'")

    assert expire_uploads(db, store) == 0
    assert store.exists(staging_key(upload_id))


# --- the sweep ------------------------------------------------------------


def test_a_sweep_reports_what_it_changed(engine):
    reaper = Reaper(engine, load_settings(), interval_seconds=1)
    report = reaper.sweep()
    assert isinstance(report.summary(), str)


def test_an_unchanged_sweep_says_so(engine):
    reaper = Reaper(engine, load_settings(), interval_seconds=1)
    reaper.sweep()
    second = reaper.sweep()
    if not second.changed:
        assert second.summary() == "nothing to do"


def test_a_stopped_reaper_performs_no_sweeps(engine):
    reaper = Reaper(engine, load_settings(), interval_seconds=1)
    reaper._stopping.set()
    assert reaper.run_forever() == 0


def test_a_sweep_is_bounded(engine):
    reaper = Reaper(engine, load_settings(), interval_seconds=0)
    assert reaper.run_forever(max_sweeps=2) == 2
