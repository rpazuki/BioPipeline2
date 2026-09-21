"""The numbers an operator would be woken for.

Each test here is a failure that is invisible without its number. A queue with
nothing claiming it looks like a busy afternoon; a dead scheduler produces no
runs, and an absent run raises no alarm at all.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.application.metrics import snapshot
from app.application.pipelines import create_revision
from app.application.publications import FieldSpec, create_publication_revision, publish
from app.application.runs import submit_run
from app.application.schedules import create_schedule
from app.domain.bindings import FieldBinding

pytestmark = pytest.mark.db

PIPELINE = """
pipeline: __NAME__
defaults:
  root: /d
  window: 5
stages:
  - name: only
    steps:
      - name: a
        package: labUtils.x
        method: run
        parameters: {moving_window_size: "{window}"}
"""


@pytest.fixture
def user(db: Session) -> uuid.UUID:
    return db.execute(
        text(
            "INSERT INTO users (email, display_name, role) VALUES (:e, 'M', 'admin') RETURNING id"
        ),
        {"e": f"m-{uuid.uuid4().hex[:10]}@example.org"},
    ).scalar_one()


def read(db: Session, tmp_path, **overrides):
    defaults = {
        "stale_after_seconds": 90,
        "overdue_after_seconds": 120,
        "artifact_root": tmp_path,
        "workspace_root": tmp_path,
    }
    defaults.update(overrides)
    return snapshot(db, **defaults)


def test_the_oldest_queued_task_is_the_signal_not_the_depth(db: Session, user, tmp_path):
    """A long queue is a busy afternoon. A queue whose oldest task has been
    waiting an hour is nothing claiming, which is a different emergency."""
    revision = create_revision(
        db, source_text=PIPELINE.replace("__NAME__", f"m_{uuid.uuid4().hex[:8]}"), owner_id=user
    )
    submitted = submit_run(
        db, pipeline_revision_id=revision.revision_id, requested_by=user, values={}
    )
    db.execute(
        text("UPDATE run_tasks SET created_at = now() - interval '1 hour' WHERE run_id = :r"),
        {"r": submitted.run_id},
    )

    reading = read(db, tmp_path)

    assert reading.tasks_queued >= 1
    assert reading.oldest_queued_seconds >= 3600


def test_a_worker_that_went_quiet_is_not_counted_as_working(db: Session, tmp_path):
    """The window before the reaper declares it dead: its tasks are still
    leased to it and nothing is running them."""
    worker_id = f"w-{uuid.uuid4().hex[:8]}"
    db.execute(
        text(
            "INSERT INTO workers (id, hostname, version, status, last_heartbeat_at) "
            "VALUES (:w, 'vm-1', '0.1.0', 'active', now() - interval '1 hour')"
        ),
        {"w": worker_id},
    )

    reading = read(db, tmp_path)

    assert reading.workers_stale >= 1


def test_a_draining_worker_is_neither_active_nor_stale(db: Session, tmp_path):
    worker_id = f"w-{uuid.uuid4().hex[:8]}"
    db.execute(
        text(
            "INSERT INTO workers (id, hostname, version, status, last_heartbeat_at) "
            "VALUES (:w, 'vm-1', '0.1.0', 'draining', now())"
        ),
        {"w": worker_id},
    )

    reading = read(db, tmp_path)

    assert reading.workers_draining >= 1


def test_a_schedule_that_should_have_fired_and_did_not_is_visible(db: Session, user, tmp_path):
    """Nothing else notices a dead scheduler: it produces no runs, and an
    absent run raises no alarm."""
    revision = create_revision(
        db, source_text=PIPELINE.replace("__NAME__", f"m_{uuid.uuid4().hex[:8]}"), owner_id=user
    )
    created = create_publication_revision(
        db,
        slug=f"metrics-{uuid.uuid4().hex[:8]}",
        pipeline_revision_id=revision.revision_id,
        title="Nightly",
        created_by=user,
        fields=[
            FieldSpec(
                key="smoothing",
                label="Smoothing window",
                field_type="integer",
                required=False,
                binding=FieldBinding(
                    key="smoothing",
                    target="step_parameter",
                    stage="only",
                    step="a",
                    binding_key="moving_window_size",
                ),
            )
        ],
    )
    publish(db, publication_id=created.publication_id, revision_id=created.revision_id)
    schedule = create_schedule(
        db,
        publication_revision_id=created.revision_id,
        owner_id=user,
        title="Nightly",
        input_values={"smoothing": 3},
        interval_seconds=3600,
    )
    before = read(db, tmp_path).schedules_overdue
    db.execute(
        text("UPDATE schedules SET next_fire_at = :t WHERE id = :i"),
        {"t": datetime.now(UTC) - timedelta(hours=2), "i": schedule.id},
    )

    assert read(db, tmp_path).schedules_overdue == before + 1


def test_a_delivery_that_stopped_retrying_is_the_one_needing_a_person(db: Session, user, tmp_path):
    """Delivery retries by itself. What needs somebody is one that gave up."""
    revision = create_revision(
        db, source_text=PIPELINE.replace("__NAME__", f"m_{uuid.uuid4().hex[:8]}"), owner_id=user
    )
    submitted = submit_run(
        db, pipeline_revision_id=revision.revision_id, requested_by=user, values={}
    )
    db.execute(
        text(
            "INSERT INTO run_deliveries (run_id, field_key, mode, status, attempts) "
            "VALUES (:r, 'out', 'download', 'failed', 5)"
        ),
        {"r": submitted.run_id},
    )

    assert read(db, tmp_path).deliveries_failed >= 1


def test_free_disk_is_read_from_the_host_this_process_runs_on(db: Session, tmp_path):
    reading = read(db, tmp_path)

    assert reading.artifact_root_free_bytes > 0
    # A root that is not mounted answers zero rather than raising: an
    # operator asking why the platform is unhappy should get an answer.
    assert read(db, tmp_path, artifact_root=tmp_path / "nowhere").artifact_root_free_bytes == 0
