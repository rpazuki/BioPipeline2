"""The schema must reject bad rows, not merely describe them.

Document 12 requires a test that constraints actually fire. Each test here
corresponds to a gap row: if the constraint were dropped, the test fails.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.infrastructure.db.models import IMMUTABLE_TABLES

pytestmark = pytest.mark.db


# --- helpers --------------------------------------------------------------


def _user(db: Session, email: str | None = None) -> uuid.UUID:
    """Insert a user. Emails are unique per call unless one is given."""
    return db.execute(
        text(
            "INSERT INTO users (email, display_name, role) "
            "VALUES (:email, 'Test', 'admin') RETURNING id"
        ),
        {"email": email or f"user-{uuid.uuid4().hex[:12]}@example.org"},
    ).scalar_one()


def _default_project(db: Session) -> uuid.UUID:
    return db.execute(text("SELECT id FROM projects WHERE is_default")).scalar_one()


def _pipeline_revision(db: Session, project: uuid.UUID, user: uuid.UUID) -> uuid.UUID:
    pipeline = db.execute(
        text(
            "INSERT INTO pipelines (project_id, slug, title, owner_id) "
            "VALUES (:p, :slug, 'WF', :u) RETURNING id"
        ),
        {"p": project, "u": user, "slug": f"wf-{uuid.uuid4().hex[:12]}"},
    ).scalar_one()
    return db.execute(
        text(
            "INSERT INTO pipeline_revisions "
            "(pipeline_id, version, source_text, graph_hash, created_by) "
            "VALUES (:w, 1, 'x', 'h', :u) RETURNING id"
        ),
        {"w": pipeline, "u": user},
    ).scalar_one()


# --- seed -----------------------------------------------------------------


def test_the_default_project_is_seeded(db: Session):
    row = db.execute(text("SELECT slug FROM projects WHERE is_default")).scalar_one()
    assert row == "default"


def test_only_one_default_project_is_allowed(db: Session):
    with pytest.raises(IntegrityError):
        db.execute(
            text("INSERT INTO projects (slug, title, is_default) VALUES ('second', 'Second', true)")
        )


# --- G23: immutability ----------------------------------------------------


def test_a_pipeline_revision_cannot_be_updated(db: Session):
    project, user = _default_project(db), _user(db)
    revision = _pipeline_revision(db, project, user)
    with pytest.raises(DBAPIError, match="immutable"):
        db.execute(
            text("UPDATE pipeline_revisions SET source_text = 'tampered' WHERE id = :i"),
            {"i": revision},
        )


def test_a_pipeline_revision_cannot_be_deleted(db: Session):
    project, user = _default_project(db), _user(db)
    revision = _pipeline_revision(db, project, user)
    with pytest.raises(DBAPIError, match="immutable"):
        db.execute(text("DELETE FROM pipeline_revisions WHERE id = :i"), {"i": revision})


def test_every_declared_immutable_table_has_its_trigger(db: Session, engine: Engine):
    """A table added to IMMUTABLE_TABLES without a migration is a silent hole."""
    installed = {
        row[0]
        for row in db.execute(text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")).all()
    }
    for table in IMMUTABLE_TABLES:
        assert f"trg_{table}_immutable" in installed, f"{table} is not protected"


# --- G31: publication field references ------------------------------------


def _publication_revision(db: Session) -> uuid.UUID:
    project, user = _default_project(db), _user(db)
    revision = _pipeline_revision(db, project, user)
    publication = db.execute(
        text(
            "INSERT INTO publications (project_id, slug, created_by) "
            "VALUES (:p, :slug, :u) RETURNING id"
        ),
        {"p": project, "u": user, "slug": f"pub-{uuid.uuid4().hex[:12]}"},
    ).scalar_one()
    return db.execute(
        text(
            "INSERT INTO publication_revisions "
            "(publication_id, pipeline_revision_id, version, title, created_by) "
            "VALUES (:pub, :wr, 1, 'T', :u) RETURNING id"
        ),
        {"pub": publication, "wr": revision, "u": user},
    ).scalar_one()


def test_a_field_referencing_neither_input_nor_output_is_rejected(db: Session):
    pub_rev = _publication_revision(db)
    with pytest.raises(IntegrityError, match="exactly_one_reference"):
        db.execute(
            text(
                "INSERT INTO publication_fields "
                "(publication_revision_id, key, label, field_type) "
                "VALUES (:r, 'k', 'L', 'string')"
            ),
            {"r": pub_rev},
        )


def test_a_hidden_only_rule_protects_fixed_values(db: Session):
    """A fixed value the researcher can also edit is a contradiction."""
    pub_rev = _publication_revision(db)
    project, user = _default_project(db), _user(db, "b@example.org")
    revision = _pipeline_revision(db, project, user)
    pipeline_input = db.execute(
        text(
            "INSERT INTO pipeline_inputs (pipeline_revision_id, key, primitive_type) "
            "VALUES (:r, 'threads', 'integer') RETURNING id"
        ),
        {"r": revision},
    ).scalar_one()
    with pytest.raises(IntegrityError, match="fixed_value_is_hidden"):
        db.execute(
            text(
                "INSERT INTO publication_fields "
                "(publication_revision_id, pipeline_input_id, key, label, field_type, "
                " fixed_value, visibility) "
                "VALUES (:r, :i, 'threads', 'Threads', 'integer', '8'::jsonb, 'visible')"
            ),
            {"r": pub_rev, "i": pipeline_input},
        )


def test_a_publication_cannot_point_at_another_publications_revision(db: Session):
    project, user = _default_project(db), _user(db)
    foreign_revision = _publication_revision(db)
    other = db.execute(
        text(
            "INSERT INTO publications (project_id, slug, created_by) "
            "VALUES (:p, :slug, :u) RETURNING id"
        ),
        {"p": project, "u": user, "slug": f"other-{uuid.uuid4().hex[:12]}"},
    ).scalar_one()
    with pytest.raises(DBAPIError, match="belongs to publication"):
        db.execute(
            text("UPDATE publications SET current_revision_id = :r WHERE id = :i"),
            {"r": foreign_revision, "i": other},
        )


def test_a_published_entry_must_have_a_current_revision(db: Session):
    project, user = _default_project(db), _user(db)
    with pytest.raises(IntegrityError, match="published_has_revision"):
        db.execute(
            text(
                "INSERT INTO publications (project_id, slug, status, created_by) "
                "VALUES (:p, 'no-rev', 'published', :u)"
            ),
            {"p": project, "u": user},
        )


# --- G24: leases ----------------------------------------------------------


def _run(db: Session) -> uuid.UUID:
    project, user = _default_project(db), _user(db)
    revision = _pipeline_revision(db, project, user)
    return db.execute(
        text(
            "INSERT INTO runs (project_id, pipeline_revision_id, requested_by) "
            "VALUES (:p, :w, :u) RETURNING id"
        ),
        {"p": project, "w": revision, "u": user},
    ).scalar_one()


def test_a_running_task_must_carry_a_lease(db: Session):
    """A held task with no lease is exactly the row that strands work."""
    run = _run(db)
    with pytest.raises(IntegrityError, match="held_task_has_lease"):
        db.execute(
            text(
                "INSERT INTO run_tasks (run_id, stage_key, task_key, status) "
                "VALUES (:r, 's', 't', 'running')"
            ),
            {"r": run},
        )


def test_a_queued_task_needs_no_lease(db: Session):
    run = _run(db)
    db.execute(
        text(
            "INSERT INTO run_tasks (run_id, stage_key, task_key, status) "
            "VALUES (:r, 's', 't', 'queued')"
        ),
        {"r": run},
    )


def test_a_task_cannot_depend_on_itself(db: Session):
    run = _run(db)
    task = db.execute(
        text(
            "INSERT INTO run_tasks (run_id, stage_key, task_key) VALUES (:r, 's', 't') RETURNING id"
        ),
        {"r": run},
    ).scalar_one()
    with pytest.raises(IntegrityError, match="no_self_dependency"):
        db.execute(
            text("INSERT INTO run_task_dependencies (task_id, depends_on_task_id) VALUES (:t, :t)"),
            {"t": task},
        )


# --- G26: run idempotency -------------------------------------------------


def test_the_same_idempotency_key_cannot_create_two_runs(db: Session):
    project, user = _default_project(db), _user(db)
    revision = _pipeline_revision(db, project, user)
    statement = text(
        "INSERT INTO runs (project_id, pipeline_revision_id, requested_by, idempotency_key) "
        "VALUES (:p, :w, :u, 'same-key')"
    )
    params = {"p": project, "w": revision, "u": user}
    db.execute(statement, params)
    with pytest.raises(IntegrityError, match="idempotency_key"):
        db.execute(statement, params)


def test_null_idempotency_keys_do_not_collide(db: Session):
    """The unique index is partial, so ordinary submissions are unaffected."""
    project, user = _default_project(db), _user(db)
    revision = _pipeline_revision(db, project, user)
    statement = text(
        "INSERT INTO runs (project_id, pipeline_revision_id, requested_by) VALUES (:p, :w, :u)"
    )
    params = {"p": project, "w": revision, "u": user}
    db.execute(statement, params)
    db.execute(statement, params)


def test_cancellation_fields_must_be_set_together(db: Session):
    project, user = _default_project(db), _user(db)
    revision = _pipeline_revision(db, project, user)
    with pytest.raises(IntegrityError, match="cancel_fields_together"):
        db.execute(
            text(
                "INSERT INTO runs "
                "(project_id, pipeline_revision_id, requested_by, cancel_requested_at) "
                "VALUES (:p, :w, :u, now())"
            ),
            {"p": project, "w": revision, "u": user},
        )


# --- G25: schedule firing -------------------------------------------------


def _schedule(db: Session) -> uuid.UUID:
    pub_rev = _publication_revision(db)
    user = _user(db, "sched@example.org")
    return db.execute(
        text(
            "INSERT INTO schedules "
            "(project_id, publication_revision_id, owner_id, title, interval_seconds) "
            "VALUES (:p, :r, :u, 'Nightly', 3600) RETURNING id"
        ),
        {"p": _default_project(db), "r": pub_rev, "u": user},
    ).scalar_one()


def test_one_window_can_only_fire_once(db: Session):
    """The guarantee behind 'once and only once' (G25)."""
    schedule = _schedule(db)
    statement = text(
        "INSERT INTO schedule_fires (schedule_id, fire_at, outcome) "
        "VALUES (:s, '2026-01-01T00:00:00Z', 'created')"
    )
    db.execute(statement, {"s": schedule})
    with pytest.raises(IntegrityError, match="schedule_id_fire_at"):
        db.execute(statement, {"s": schedule})


def test_a_schedule_must_pick_exactly_one_recurrence_representation(db: Session):
    pub_rev = _publication_revision(db)
    user = _user(db, "sched2@example.org")
    with pytest.raises(IntegrityError, match="exactly_one_recurrence"):
        db.execute(
            text(
                "INSERT INTO schedules "
                "(project_id, publication_revision_id, owner_id, title, rrule, interval_seconds) "
                "VALUES (:p, :r, :u, 'Both', 'FREQ=DAILY', 3600)"
            ),
            {"p": _default_project(db), "r": pub_rev, "u": user},
        )


def test_a_schedule_with_no_recurrence_is_rejected(db: Session):
    pub_rev = _publication_revision(db)
    user = _user(db, "sched3@example.org")
    with pytest.raises(IntegrityError, match="exactly_one_recurrence"):
        db.execute(
            text(
                "INSERT INTO schedules "
                "(project_id, publication_revision_id, owner_id, title) "
                "VALUES (:p, :r, :u, 'Neither')"
            ),
            {"p": _default_project(db), "r": pub_rev, "u": user},
        )


# --- G31: artifacts -------------------------------------------------------


def test_two_live_artifacts_cannot_share_a_storage_key(db: Session):
    """Otherwise the janitor deletes bytes another row still claims."""
    project = _default_project(db)
    statement = text(
        "INSERT INTO artifacts (project_id, kind, storage_key, filename) "
        "VALUES (:p, 'task_output', 'runs/1/out.txt', 'out.txt')"
    )
    db.execute(statement, {"p": project})
    with pytest.raises(IntegrityError, match="storage_key"):
        db.execute(statement, {"p": project})


def test_a_deleted_artifact_frees_its_storage_key(db: Session):
    """The unique index is partial so a purged key can be reused."""
    project = _default_project(db)
    db.execute(
        text(
            "INSERT INTO artifacts (project_id, kind, storage_key, filename, deleted_at) "
            "VALUES (:p, 'task_output', 'runs/2/out.txt', 'out.txt', now())"
        ),
        {"p": project},
    )
    db.execute(
        text(
            "INSERT INTO artifacts (project_id, kind, storage_key, filename) "
            "VALUES (:p, 'task_output', 'runs/2/out.txt', 'out.txt')"
        ),
        {"p": project},
    )


def test_a_malformed_checksum_is_rejected(db: Session):
    project = _default_project(db)
    with pytest.raises(IntegrityError, match="checksum_format"):
        db.execute(
            text(
                "INSERT INTO artifacts (project_id, kind, storage_key, filename, checksum_sha256) "
                "VALUES (:p, 'task_output', 'runs/3/o', 'o', 'NOTAHASH')"
            ),
            {"p": project},
        )


# --- G16: delivery --------------------------------------------------------


def test_a_shared_delivery_must_name_a_root(db: Session):
    run = _run(db)
    with pytest.raises(IntegrityError, match="shared_has_target_root"):
        db.execute(
            text(
                "INSERT INTO run_deliveries (run_id, field_key, mode) "
                "VALUES (:r, 'report', 'shared')"
            ),
            {"r": run},
        )


def test_a_download_delivery_needs_no_root(db: Session):
    run = _run(db)
    db.execute(
        text(
            "INSERT INTO run_deliveries (run_id, field_key, mode) VALUES (:r, 'report', 'download')"
        ),
        {"r": run},
    )


# --- G14: uploads ---------------------------------------------------------


def test_an_upload_cannot_receive_more_than_it_declared(db: Session):
    project, user = _default_project(db), _user(db)
    with pytest.raises(IntegrityError, match="not_over_declared_size"):
        db.execute(
            text(
                "INSERT INTO uploads "
                "(project_id, owner_id, filename, storage_key, declared_size_bytes, "
                " received_bytes, expires_at) "
                "VALUES (:p, :u, 'f.bam', 'k', 100, 200, now() + interval '1 day')"
            ),
            {"p": project, "u": user},
        )


def test_a_completed_upload_must_have_an_artifact(db: Session):
    project, user = _default_project(db), _user(db)
    with pytest.raises(IntegrityError, match="completed_has_artifact"):
        db.execute(
            text(
                "INSERT INTO uploads "
                "(project_id, owner_id, filename, storage_key, status, expires_at) "
                "VALUES (:p, :u, 'f.bam', 'k2', 'completed', now() + interval '1 day')"
            ),
            {"p": project, "u": user},
        )


# --- G33: type version pinning -------------------------------------------


def test_a_saved_value_must_pin_an_existing_type_version(db: Session):
    project, user = _default_project(db), _user(db)
    with pytest.raises(IntegrityError, match="type_definition"):
        db.execute(
            text(
                "INSERT INTO saved_values "
                "(project_id, user_id, type_key, type_version, name, value) "
                "VALUES (:p, :u, 'ghost', 1, 'n', '{}'::jsonb)"
            ),
            {"p": project, "u": user},
        )


# --- enum CHECK constraints ----------------------------------------------


def test_an_invalid_run_status_is_rejected(db: Session):
    project, user = _default_project(db), _user(db)
    revision = _pipeline_revision(db, project, user)
    with pytest.raises(IntegrityError, match="status_valid"):
        db.execute(
            text(
                "INSERT INTO runs (project_id, pipeline_revision_id, requested_by, status) "
                "VALUES (:p, :w, :u, 'nonsense')"
            ),
            {"p": project, "w": revision, "u": user},
        )


def test_email_uniqueness_is_case_insensitive(db: Session):
    _user(db, "Case@Example.org")
    with pytest.raises(IntegrityError, match="email_lower"):
        _user(db, "case@example.org")


def test_a_slug_must_be_url_safe(db: Session):
    with pytest.raises(IntegrityError, match="slug_format"):
        db.execute(text("INSERT INTO projects (slug, title) VALUES ('Not A Slug!', 'X')"))
