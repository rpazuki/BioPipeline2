"""Application services against a real database.

These are the transactional use cases: compiling a document into an immutable
revision, and turning a submission into a run with its task graph. Both touch
several tables at once, so both are tested where that actually matters.
"""

from __future__ import annotations

import pathlib
import uuid

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.application.pipelines import (
    CompilationFailed,
    create_revision,
    load_compiled,
)
from app.application.runs import (
    SubmissionRejected,
    get_run,
    release_ready_tasks,
    submit_run,
)
from app.domain.materialise import folder_items, mapping_file_items
from app.infrastructure.pipeline_loader import DirectoryLibraryLoader

pytestmark = pytest.mark.db

ROOT = pathlib.Path(__file__).resolve().parents[3]
COMPONENTS = ROOT / "examples/components"
GROWTH = (ROOT / "examples/pipelines/od600_growth_rates.yaml").read_text()

VALUES = {"data_root": "/data/run1", "mapping_yaml": "/data/run1/mapping.yaml"}
MAPPING = {"a.csv": "a_meta.csv", "b.csv": "b_meta.csv"}


def enumerate_mapping(_fanout):
    return mapping_file_items(MAPPING)


@pytest.fixture
def user(db: Session) -> uuid.UUID:
    return db.execute(
        text(
            "INSERT INTO users (email, display_name, role) "
            "VALUES (:e, 'Test', 'admin') RETURNING id"
        ),
        {"e": f"u-{uuid.uuid4().hex[:10]}@example.org"},
    ).scalar_one()


@pytest.fixture
def loader():
    return DirectoryLibraryLoader(COMPONENTS)


SIMPLE = """
pipeline: simple
defaults: {root: /d}
stages:
  - name: only
    steps:
      - {name: a, package: labUtils.x, method: run, parameters: {p: "{root}/in"}}
    outputs:
      out: {path: "{root}/out"}
"""


# --- creating revisions ---------------------------------------------------


def test_a_document_becomes_an_immutable_revision(db: Session, user, loader):
    created = create_revision(db, source_text=GROWTH, owner_id=user, load_library=loader)
    assert created.version == 1
    assert created.graph_hash.startswith("sha256:")
    assert not created.reused


def test_the_stored_ir_reads_back_and_is_executable(db: Session, user, loader):
    created = create_revision(db, source_text=GROWTH, owner_id=user, load_library=loader)
    compiled = load_compiled(db, created.revision_id)
    assert compiled.graph_hash == created.graph_hash
    assert set(compiled.stage_keys) == {"fit:no_replicates", "fit:replicates"}


def test_public_inputs_are_normalised_for_querying(db: Session, user, loader):
    created = create_revision(db, source_text=GROWTH, owner_id=user, load_library=loader)
    keys = (
        db.execute(
            text("SELECT key FROM pipeline_inputs WHERE pipeline_revision_id = :r ORDER BY key"),
            {"r": created.revision_id},
        )
        .scalars()
        .all()
    )
    assert keys == ["data_root", "mapping_yaml"]


def test_outputs_are_deduplicated_across_matrix_rows(db: Session, user, loader):
    """Two variants declare the same output name; the public surface is the
    set of names, not one row's copy."""
    created = create_revision(db, source_text=GROWTH, owner_id=user, load_library=loader)
    keys = (
        db.execute(
            text("SELECT key FROM pipeline_outputs WHERE pipeline_revision_id = :r"),
            {"r": created.revision_id},
        )
        .scalars()
        .all()
    )
    assert keys == ["results"]


def test_a_broken_document_never_reaches_the_database(db: Session, user):
    broken = SIMPLE.replace('"{root}/in"', '"{nope}/in"')
    with pytest.raises(CompilationFailed) as caught:
        create_revision(db, source_text=broken, owner_id=user)
    assert caught.value.details["errors"]
    # Scoped to this test's own user: a global count would depend on the order
    # tests run in, since other tests commit rows.
    assert (
        db.execute(
            text("SELECT count(*) FROM pipeline_revisions WHERE created_by = :u"),
            {"u": user},
        ).scalar_one()
        == 0
    )


def test_editing_a_document_creates_a_new_version(db: Session, user):
    first = create_revision(db, source_text=SIMPLE, owner_id=user)
    second = create_revision(db, source_text=SIMPLE.replace("/d", "/other"), owner_id=user)
    assert (first.version, second.version) == (1, 2)
    assert first.pipeline_id == second.pipeline_id
    assert first.graph_hash != second.graph_hash


def test_recompiling_unchanged_source_reuses_the_revision(db: Session, user):
    """Compilation is deterministic and revisions are immutable, so a save
    button pressed twice should not produce two versions."""
    first = create_revision(db, source_text=SIMPLE, owner_id=user)
    second = create_revision(db, source_text=SIMPLE, owner_id=user)
    assert second.reused
    assert second.revision_id == first.revision_id
    assert second.version == 1


def test_a_stored_revision_cannot_be_edited(db: Session, user):
    """The immutability trigger, reached through the service."""
    created = create_revision(db, source_text=SIMPLE, owner_id=user)
    from sqlalchemy.exc import DBAPIError

    with pytest.raises(DBAPIError, match="immutable"):
        db.execute(
            text("UPDATE pipeline_revisions SET source_text = 'x' WHERE id = :i"),
            {"i": created.revision_id},
        )


# --- submitting runs ------------------------------------------------------


def _revision(db: Session, user, loader) -> uuid.UUID:
    return create_revision(db, source_text=GROWTH, owner_id=user, load_library=loader).revision_id


def test_a_submission_creates_a_run_and_its_tasks(db: Session, user, loader):
    revision = _revision(db, user, loader)
    submitted = submit_run(
        db,
        pipeline_revision_id=revision,
        requested_by=user,
        values=VALUES,
        enumerate_fanout=enumerate_mapping,
    )
    # 2 matrix rows x 2 mapping entries
    assert submitted.task_count == 4
    view = get_run(db, submitted.run_id)
    assert view.status == "queued"
    assert view.total_tasks == 4


def test_tasks_with_no_dependencies_start_queued(db: Session, user, loader):
    revision = _revision(db, user, loader)
    submitted = submit_run(
        db,
        pipeline_revision_id=revision,
        requested_by=user,
        values=VALUES,
        enumerate_fanout=enumerate_mapping,
    )
    view = get_run(db, submitted.run_id)
    assert view.task_counts == {"queued": 4}


def test_submitted_values_are_recorded_with_their_source(db: Session, user, loader):
    revision = _revision(db, user, loader)
    submitted = submit_run(
        db,
        pipeline_revision_id=revision,
        requested_by=user,
        values=VALUES,
        enumerate_fanout=enumerate_mapping,
    )
    rows = db.execute(
        text("SELECT field_key, value_source FROM run_field_values WHERE run_id = :r"),
        {"r": submitted.run_id},
    ).all()
    assert {r.field_key for r in rows} == set(VALUES)
    assert {r.value_source for r in rows} == {"researcher"}


def test_the_task_spec_carries_everything_a_worker_needs(db: Session, user, loader):
    revision = _revision(db, user, loader)
    submitted = submit_run(
        db,
        pipeline_revision_id=revision,
        requested_by=user,
        values=VALUES,
        enumerate_fanout=enumerate_mapping,
    )
    spec = db.execute(
        text("SELECT task_spec FROM run_tasks WHERE run_id = :r LIMIT 1"),
        {"r": submitted.run_id},
    ).scalar_one()
    assert {"stage", "steps", "inputs", "outputs", "item"} <= set(spec)
    assert spec["steps"][0]["package"].startswith("labUtils")
    # Every reference is finished by now.
    assert "{" not in spec["inputs"]["raw_data"]


def test_resource_requests_are_persisted_for_admission_control(db: Session, user, loader):
    revision = _revision(db, user, loader)
    submitted = submit_run(
        db,
        pipeline_revision_id=revision,
        requested_by=user,
        values=VALUES,
        enumerate_fanout=enumerate_mapping,
    )
    row = db.execute(
        text(
            "SELECT task_class, cpu_request_millicores, memory_request_bytes "
            "FROM run_tasks WHERE run_id = :r LIMIT 1"
        ),
        {"r": submitted.run_id},
    ).one()
    assert row.task_class == "standard"
    assert row.cpu_request_millicores > 0 and row.memory_request_bytes > 0


def test_missing_values_are_rejected_before_anything_is_written(db: Session, user, loader):
    revision = _revision(db, user, loader)
    with pytest.raises(SubmissionRejected):
        submit_run(
            db,
            pipeline_revision_id=revision,
            requested_by=user,
            values={},
            enumerate_fanout=enumerate_mapping,
        )
    assert (
        db.execute(
            text("SELECT count(*) FROM runs WHERE requested_by = :u"), {"u": user}
        ).scalar_one()
        == 0
    )


def test_an_empty_fanout_is_rejected(db: Session, user, loader):
    revision = _revision(db, user, loader)
    with pytest.raises(SubmissionRejected, match="error"):
        submit_run(
            db,
            pipeline_revision_id=revision,
            requested_by=user,
            values=VALUES,
            enumerate_fanout=lambda _f: [],
        )


def test_an_unknown_revision_is_rejected(db: Session, user):
    from app.domain.errors import ValidationFailed

    with pytest.raises(ValidationFailed, match="does not exist"):
        submit_run(
            db,
            pipeline_revision_id=uuid.uuid4(),
            requested_by=user,
            values={},
        )


# --- idempotency ----------------------------------------------------------


def test_the_same_idempotency_key_returns_the_first_run(db: Session, user, loader):
    revision = _revision(db, user, loader)
    kwargs = dict(
        pipeline_revision_id=revision,
        requested_by=user,
        values=VALUES,
        enumerate_fanout=enumerate_mapping,
        idempotency_key="submit-1",
    )
    first = submit_run(db, **kwargs)
    second = submit_run(db, **kwargs)
    assert second.reused
    assert second.run_id == first.run_id
    assert second.task_count == first.task_count
    assert (
        db.execute(
            text("SELECT count(*) FROM runs WHERE requested_by = :u"), {"u": user}
        ).scalar_one()
        == 1
    )


def test_submissions_without_a_key_are_independent(db: Session, user, loader):
    revision = _revision(db, user, loader)
    kwargs = dict(
        pipeline_revision_id=revision,
        requested_by=user,
        values=VALUES,
        enumerate_fanout=enumerate_mapping,
    )
    first = submit_run(db, **kwargs)
    second = submit_run(db, **kwargs)
    assert first.run_id != second.run_id


def test_a_concurrent_duplicate_submission_resolves_to_one_run(
    engine: Engine, user_email="race@example.org"
):
    """Two submissions racing on the same key must not both create a run.

    Needs committed rows, so it cannot use the transactional fixture: a
    rolled-back transaction on one connection is invisible to another.
    """
    make = sessionmaker(bind=engine, expire_on_commit=False)
    setup = make()
    owner = setup.execute(
        text(
            "INSERT INTO users (email, display_name, role) "
            "VALUES (:e, 'Race', 'admin') RETURNING id"
        ),
        {"e": f"race-{uuid.uuid4().hex[:8]}@example.org"},
    ).scalar_one()
    revision = create_revision(setup, source_text=SIMPLE, owner_id=owner).revision_id
    setup.commit()
    setup.close()

    first, second = make(), make()
    try:
        a = submit_run(
            first,
            pipeline_revision_id=revision,
            requested_by=owner,
            values={},
            idempotency_key="race",
        )
        first.commit()
        b = submit_run(
            second,
            pipeline_revision_id=revision,
            requested_by=owner,
            values={},
            idempotency_key="race",
        )
        second.commit()
        assert b.reused and b.run_id == a.run_id
    finally:
        for session in (first, second):
            session.rollback()
            session.close()
        # Delete the runs, which cascades to their tasks. Nothing else can go:
        # a pipeline revision is immutable by design, so DELETE is refused by
        # the trigger. Attempting it aborts this whole cleanup transaction and
        # leaves claimable tasks behind, which then leak into the scheduler
        # tests -- exactly what happened when this was written the obvious way.
        cleanup = make()
        cleanup.execute(text("DELETE FROM runs WHERE requested_by = :u"), {"u": owner})
        cleanup.commit()
        cleanup.close()


# --- dependencies and release --------------------------------------------


TWO_STAGE = """
pipeline: two_stage
defaults: {root: /d}
stages:
  - name: first
    fanout: {type: folders, data_dir: "{root}"}
    steps:
      - {name: a, package: labUtils.x, method: run}
    outputs:
      out: {path: "{root}/{item.stem}"}
  - name: second
    needs: [first]
    steps:
      - {name: b, package: labUtils.x, method: collate}
"""


def test_a_dependent_task_starts_created_not_queued(db: Session, user):
    revision = create_revision(db, source_text=TWO_STAGE, owner_id=user).revision_id
    submitted = submit_run(
        db,
        pipeline_revision_id=revision,
        requested_by=user,
        values={},
        enumerate_fanout=lambda _f: folder_items(["a", "b"]),
    )
    view = get_run(db, submitted.run_id)
    assert view.task_counts == {"queued": 2, "created": 1}


def test_dependency_edges_are_persisted(db: Session, user):
    revision = create_revision(db, source_text=TWO_STAGE, owner_id=user).revision_id
    submitted = submit_run(
        db,
        pipeline_revision_id=revision,
        requested_by=user,
        values={},
        enumerate_fanout=lambda _f: folder_items(["a", "b"]),
    )
    edges = db.execute(
        text(
            "SELECT count(*) FROM run_task_dependencies d "
            "JOIN run_tasks t ON t.id = d.task_id WHERE t.run_id = :r"
        ),
        {"r": submitted.run_id},
    ).scalar_one()
    assert edges == 2  # the gather waits for both upstream tasks


def test_a_task_is_released_only_when_every_dependency_succeeded(db: Session, user):
    revision = create_revision(db, source_text=TWO_STAGE, owner_id=user).revision_id
    submitted = submit_run(
        db,
        pipeline_revision_id=revision,
        requested_by=user,
        values={},
        enumerate_fanout=lambda _f: folder_items(["a", "b"]),
    )
    run_id = submitted.run_id

    # Nothing finished yet.
    assert release_ready_tasks(db, run_id) == []

    # One of two upstream tasks succeeds: still not ready.
    # The suffix is bound, not inlined: text() would read ":a" as a parameter.
    db.execute(
        text(
            "UPDATE run_tasks SET status = 'succeeded' WHERE run_id = :r "
            "AND stage_key = 'first' AND task_key LIKE :suffix"
        ),
        {"r": run_id, "suffix": "%:a"},
    )
    assert release_ready_tasks(db, run_id) == []

    # Both succeed: released.
    db.execute(
        text("UPDATE run_tasks SET status = 'succeeded' WHERE run_id = :r AND stage_key = 'first'"),
        {"r": run_id},
    )
    released = release_ready_tasks(db, run_id)
    assert len(released) == 1
    assert get_run(db, run_id).task_counts == {"succeeded": 2, "queued": 1}
