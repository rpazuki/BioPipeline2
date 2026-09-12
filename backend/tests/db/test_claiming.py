"""Task claiming and admission control.

These are the concurrency tests document 12 requires: two workers must not
claim one task, the budget must not be over-committed, and an expired lease
must return work to the queue rather than stranding it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.infrastructure.db.claiming import (
    Budget,
    Committed,
    claim_next_task,
    committed,
    fits,
    reclaim_expired_leases,
)

pytestmark = pytest.mark.db


def _fake_hash() -> str:
    """A well-formed graph hash for fixtures.

    The column enforces `sha256:` plus 64 hex characters, so a placeholder
    like 'h' is rejected -- which is the constraint doing its job.
    """
    return "sha256:" + uuid.uuid4().hex + uuid.uuid4().hex


GIB = 1024**3


# --- the pure policy ------------------------------------------------------


def _used(cpu=0, memory=0, tasks=0, exclusive=False) -> Committed:
    return Committed(
        cpu_millicores=cpu, memory_bytes=memory, task_count=tasks, has_exclusive=exclusive
    )


BUDGET = Budget(cpu_millicores=4000, memory_bytes=12 * GIB, max_concurrent_tasks=4)


def _fits(used: Committed, cpu: int, memory: int, exclusive: bool = False) -> bool:
    return fits(
        budget=BUDGET, used=used, cpu_request=cpu, memory_request=memory, exclusive=exclusive
    )


def test_a_small_task_fits_an_empty_host():
    assert _fits(_used(), 500, GIB)


def test_a_task_larger_than_the_whole_budget_never_fits():
    assert not _fits(_used(), 8000, GIB)
    assert not _fits(_used(), 500, 99 * GIB)


def test_a_task_requesting_the_whole_budget_runs_alone():
    """This is how heavy work is kept sequential without a separate queue."""
    assert _fits(_used(), 4000, 12 * GIB)
    assert not _fits(_used(cpu=500, memory=GIB, tasks=1), 4000, 12 * GIB)


def test_small_tasks_pack_together():
    used = _used(cpu=1000, memory=2 * GIB, tasks=1)
    assert _fits(used, 1000, 2 * GIB)


def test_cpu_exhaustion_blocks_admission():
    used = _used(cpu=3800, memory=GIB, tasks=2)
    assert not _fits(used, 500, GIB)


def test_memory_exhaustion_blocks_admission():
    used = _used(cpu=500, memory=11 * GIB, tasks=1)
    assert not _fits(used, 500, 2 * GIB)


def test_the_task_count_cap_blocks_admission():
    used = _used(cpu=100, memory=GIB, tasks=4)
    assert not _fits(used, 100, GIB)


def test_an_exclusive_task_requires_an_idle_host():
    assert _fits(_used(), 100, GIB, exclusive=True)
    assert not _fits(_used(tasks=1, cpu=100, memory=GIB), 100, GIB, exclusive=True)


def test_nothing_is_admitted_while_an_exclusive_task_holds_the_host():
    used = _used(cpu=100, memory=GIB, tasks=1, exclusive=True)
    assert not _fits(used, 1, 1)


# --- against the database -------------------------------------------------


def _task(db: Session, *, cpu=1000, memory=2 * GIB, exclusive=False, status="queued") -> uuid.UUID:
    user = db.execute(
        text(
            "INSERT INTO users (email, display_name, role) VALUES (:e, 'T', 'admin') RETURNING id"
        ),
        {"e": f"u-{uuid.uuid4().hex[:10]}@example.org"},
    ).scalar_one()
    project = db.execute(text("SELECT id FROM projects WHERE is_default")).scalar_one()
    pipeline = db.execute(
        text(
            "INSERT INTO pipelines (project_id, slug, title, owner_id) "
            "VALUES (:p, :s, 'P', :u) RETURNING id"
        ),
        {"p": project, "u": user, "s": f"p-{uuid.uuid4().hex[:10]}"},
    ).scalar_one()
    revision = db.execute(
        text(
            "INSERT INTO pipeline_revisions "
            "(pipeline_id, version, source_text, graph_hash, created_by) "
            "VALUES (:pl, 1, 'x', :hash, :u) RETURNING id"
        ),
        {"pl": pipeline, "u": user, "hash": _fake_hash()},
    ).scalar_one()
    run = db.execute(
        text(
            "INSERT INTO runs (project_id, pipeline_revision_id, requested_by) "
            "VALUES (:p, :r, :u) RETURNING id"
        ),
        {"p": project, "r": revision, "u": user},
    ).scalar_one()
    # A task holding resources must also carry a lease, per the schema's
    # ck_run_tasks_held_task_has_lease constraint. Computed here rather than
    # in SQL so the status parameter has one unambiguous type.
    holds = status in {"claimed", "running"}
    return db.execute(
        text(
            "INSERT INTO run_tasks "
            "(run_id, stage_key, task_key, status, dependencies_satisfied, "
            " cpu_request_millicores, memory_request_bytes, exclusive, "
            " claimed_by, lease_expires_at) "
            "VALUES (:run, 's', :k, :st, true, :cpu, :mem, :ex, :worker, :lease) "
            "RETURNING id"
        ),
        {
            "run": run,
            "k": f"t-{uuid.uuid4().hex[:8]}",
            "st": status,
            "cpu": cpu,
            "mem": memory,
            "ex": exclusive,
            "worker": _worker(db, "w-seed") if holds else None,
            "lease": (datetime.now(UTC) + timedelta(hours=1)) if holds else None,
        },
    ).scalar_one()


def _worker(db: Session, name: str) -> str:
    db.execute(
        text(
            "INSERT INTO workers (id, hostname, version, status) "
            "VALUES (:i, 'localhost', '0.1.0', 'active') ON CONFLICT (id) DO NOTHING"
        ),
        {"i": name},
    )
    return name


def test_committed_sums_only_tasks_that_hold_resources(db: Session):
    _task(db, cpu=1000, memory=GIB, status="running")
    _task(db, cpu=500, memory=GIB, status="claimed")
    _task(db, cpu=2000, memory=4 * GIB, status="queued")
    _task(db, cpu=2000, memory=4 * GIB, status="succeeded")
    used = committed(db)
    assert used.cpu_millicores == 1500
    assert used.task_count == 2


def test_a_queued_task_is_claimed_and_leased(db: Session):
    task = _task(db, cpu=500, memory=GIB)
    worker = _worker(db, "w-1")
    claimed = claim_next_task(db, worker_id=worker, budget=BUDGET, lease_seconds=120)
    assert claimed == task
    row = db.execute(
        text(
            "SELECT status, claimed_by, lease_expires_at, attempt_count "
            "FROM run_tasks WHERE id = :i"
        ),
        {"i": task},
    ).one()
    assert row.status == "claimed"
    assert row.claimed_by == worker
    assert row.lease_expires_at is not None
    assert row.attempt_count == 1


def test_a_task_that_does_not_fit_is_not_claimed(db: Session):
    """None means 'nothing admissible', not 'queue empty'."""
    _task(db, cpu=3900, memory=GIB, status="running")
    _task(db, cpu=1000, memory=GIB, status="queued")
    worker = _worker(db, "w-2")
    assert claim_next_task(db, worker_id=worker, budget=BUDGET, lease_seconds=120) is None


def test_an_exclusive_task_is_not_claimed_while_others_run(db: Session):
    _task(db, cpu=100, memory=GIB, status="running")
    _task(db, cpu=100, memory=GIB, exclusive=True)
    worker = _worker(db, "w-3")
    assert claim_next_task(db, worker_id=worker, budget=BUDGET, lease_seconds=120) is None


def test_an_exclusive_task_is_claimed_on_an_idle_host(db: Session):
    task = _task(db, cpu=4000, memory=12 * GIB, exclusive=True)
    worker = _worker(db, "w-4")
    assert claim_next_task(db, worker_id=worker, budget=BUDGET, lease_seconds=120) == task


def test_a_task_whose_dependencies_are_unmet_is_not_claimed(db: Session):
    task = _task(db)
    db.execute(
        text("UPDATE run_tasks SET dependencies_satisfied = false WHERE id = :i"), {"i": task}
    )
    worker = _worker(db, "w-5")
    assert claim_next_task(db, worker_id=worker, budget=BUDGET, lease_seconds=120) is None


def test_a_task_of_a_cancelled_run_is_not_claimed(db: Session):
    task = _task(db)
    db.execute(
        text(
            "UPDATE runs SET cancel_requested_at = now(), cancel_requested_by = requested_by "
            "WHERE id = (SELECT run_id FROM run_tasks WHERE id = :i)"
        ),
        {"i": task},
    )
    worker = _worker(db, "w-6")
    assert claim_next_task(db, worker_id=worker, budget=BUDGET, lease_seconds=120) is None


def test_two_workers_cannot_claim_the_same_task(engine: Engine):
    """The property SKIP LOCKED exists to provide.

    This test cannot use the transactional ``db`` fixture: that wraps the test
    in a rolled-back transaction on one connection, so its rows are invisible
    to any other connection. Two concurrent claimers need genuinely committed
    data, so the fixture rows are created and cleaned up explicitly here.
    """
    make = sessionmaker(bind=engine, expire_on_commit=False)
    setup = make()
    task = _task(setup, cpu=100, memory=GIB)
    _worker(setup, "w-a")
    _worker(setup, "w-b")
    setup.commit()
    setup.close()

    first, second = make(), make()
    try:
        got_first = claim_next_task(first, worker_id="w-a", budget=BUDGET, lease_seconds=60)
        got_second = claim_next_task(second, worker_id="w-b", budget=BUDGET, lease_seconds=60)
        assert got_first == task
        assert got_second is None, "second worker claimed a task the first already held"
    finally:
        first.rollback()
        second.rollback()
        first.close()
        second.close()
        teardown = make()
        run_id = teardown.execute(
            text("SELECT run_id FROM run_tasks WHERE id = :i"), {"i": task}
        ).scalar_one_or_none()
        teardown.execute(text("DELETE FROM run_tasks WHERE id = :i"), {"i": task})
        if run_id is not None:
            teardown.execute(text("DELETE FROM runs WHERE id = :i"), {"i": run_id})
        teardown.execute(
            text(
                "UPDATE run_tasks SET claimed_by = NULL WHERE claimed_by IN ('w-a','w-b','w-seed')"
            )
        )
        teardown.execute(text("DELETE FROM workers WHERE id IN ('w-a','w-b')"))
        teardown.commit()
        teardown.close()


# --- lease expiry ---------------------------------------------------------


def test_an_expired_lease_returns_the_task_to_the_queue(db: Session):
    task = _task(db, status="running")
    db.execute(
        text(
            "UPDATE run_tasks SET lease_expires_at = now() - interval '1 minute', "
            "attempt_count = 1 WHERE id = :i"
        ),
        {"i": task},
    )
    reclaimed = reclaim_expired_leases(db, poison_limit=3)
    assert (task, "queued") in reclaimed
    row = db.execute(
        text("SELECT status, claimed_by, status_reason FROM run_tasks WHERE id = :i"),
        {"i": task},
    ).one()
    assert row.status == "queued"
    assert row.claimed_by is None
    assert "lease expired" in row.status_reason


def test_a_live_lease_is_left_alone(db: Session):
    task = _task(db, status="running")
    assert reclaim_expired_leases(db, poison_limit=3) == []
    status = db.execute(
        text("SELECT status FROM run_tasks WHERE id = :i"), {"i": task}
    ).scalar_one()
    assert status == "running"


def test_a_task_that_keeps_losing_its_lease_eventually_fails(db: Session):
    """The poison limit: without it a task that never reports back cycles forever."""
    task = _task(db, status="running")
    db.execute(
        text(
            "UPDATE run_tasks SET lease_expires_at = now() - interval '1 minute', "
            "attempt_count = 5 WHERE id = :i"
        ),
        {"i": task},
    )
    reclaimed = reclaim_expired_leases(db, poison_limit=3)
    assert (task, "failed") in reclaimed
    row = db.execute(
        text("SELECT status, status_reason, finished_at FROM run_tasks WHERE id = :i"),
        {"i": task},
    ).one()
    assert row.status == "failed"
    assert "without a clean outcome" in row.status_reason
    assert row.finished_at is not None


# --- fairness: bounded backfill, then reservation -------------------------
#
# The policy these tests pin down was previously described in a comment and
# not implemented at all. A documented invariant with no code is worse than a
# known-imperfect policy, so each branch has a test.


def _aged_task(db: Session, *, cpu: int, memory: int, age_seconds: int, exclusive=False):
    task = _task(db, cpu=cpu, memory=memory, exclusive=exclusive)
    db.execute(
        text("UPDATE run_tasks SET created_at = now() - make_interval(secs => :age) WHERE id = :i"),
        {"i": task, "age": age_seconds},
    )
    return task


GRACE = Budget(
    cpu_millicores=4000,
    memory_bytes=12 * GIB,
    max_concurrent_tasks=4,
    starvation_grace_seconds=900,
)


def test_a_small_task_backfills_around_a_recently_queued_large_one(db: Session):
    """Within the grace period, free capacity is used rather than held."""
    _task(db, cpu=3000, memory=8 * GIB, status="running")
    _aged_task(db, cpu=4000, memory=12 * GIB, age_seconds=10)  # cannot fit
    small = _aged_task(db, cpu=500, memory=GIB, age_seconds=5)  # fits
    worker = _worker(db, "w-bf1")
    assert claim_next_task(db, worker_id=worker, budget=GRACE, lease_seconds=60) == small


def test_a_starved_large_task_reserves_capacity_after_the_grace_period(db: Session):
    """Past the grace period, small work no longer overtakes it."""
    _task(db, cpu=3000, memory=8 * GIB, status="running")
    _aged_task(db, cpu=4000, memory=12 * GIB, age_seconds=2000)  # now reserving
    _aged_task(db, cpu=500, memory=GIB, age_seconds=5)  # would fit
    worker = _worker(db, "w-bf2")
    assert claim_next_task(db, worker_id=worker, budget=GRACE, lease_seconds=60) is None


def test_a_reserving_task_is_claimed_as_soon_as_it_fits(db: Session):
    big = _aged_task(db, cpu=4000, memory=12 * GIB, age_seconds=2000)
    worker = _worker(db, "w-bf3")
    assert claim_next_task(db, worker_id=worker, budget=GRACE, lease_seconds=60) == big


def test_a_task_that_fits_is_claimed_rather_than_treated_as_starved(db: Session):
    """Ageing alone does not make a task reserving: it must also not fit."""
    big = _aged_task(db, cpu=2000, memory=4 * GIB, age_seconds=2000)
    _aged_task(db, cpu=500, memory=GIB, age_seconds=5)
    worker = _worker(db, "w-bf4")
    # Nothing is running, so the aged task fits and simply runs.
    assert claim_next_task(db, worker_id=worker, budget=GRACE, lease_seconds=60) == big


def test_the_reservation_barrier_is_strict(db: Session):
    """No "fits alongside" exemption exists, because it is unreachable.

    If used + reserved + candidate fitted the budget, the reserving task would
    itself have been admitted and would not be reserving.
    """
    _task(db, cpu=3000, memory=8 * GIB, status="running")
    _aged_task(db, cpu=2000, memory=4 * GIB, age_seconds=2000)  # cannot fit -> reserves
    _aged_task(db, cpu=100, memory=GIB, age_seconds=5)  # would fit, but is blocked
    worker = _worker(db, "w-bf7")
    assert claim_next_task(db, worker_id=worker, budget=GRACE, lease_seconds=60) is None


def test_the_oldest_reserving_task_is_preferred_over_a_newer_one(db: Session):
    older = _aged_task(db, cpu=1000, memory=2 * GIB, age_seconds=3000)
    _aged_task(db, cpu=1000, memory=2 * GIB, age_seconds=2000)
    worker = _worker(db, "w-bf5")
    assert claim_next_task(db, worker_id=worker, budget=GRACE, lease_seconds=60) == older


def test_reservation_does_not_block_when_nothing_is_starved(db: Session):
    """The common case: no reservations, ordinary admission."""
    task = _aged_task(db, cpu=500, memory=GIB, age_seconds=5)
    worker = _worker(db, "w-bf6")
    assert claim_next_task(db, worker_id=worker, budget=GRACE, lease_seconds=60) == task
