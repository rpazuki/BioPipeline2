"""An uploaded file, from staging area to the inside of a container.

The upload protocol itself is tested over HTTP. What is here is the other
half — the part that makes an upload worth having — where the artifact it
minted is put in the run's workspace under the path the task was told to read.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.application.pipelines import create_revision
from app.application.runs import SubmissionRejected, submit_run
from app.application.uploads import (
    UploadRejected,
    begin_upload,
    complete_upload,
    stage_inputs,
    staged_inputs_for_run,
    staging_key,
)
from app.domain.task_contract import ResourceLimits
from app.infrastructure.artifacts import PosixArtifactStore
from app.infrastructure.execution.docker import DockerAdapter
from app.infrastructure.workspace import create_workspace
from app.settings import load_settings
from app.workers.executor import execute_task

pytestmark = pytest.mark.db

DOC = """
pipeline: __NAME__
defaults: {sample_file: $WILL_PROVIDE$}
inputs:
  sample_file: {accept: file, sources: [upload]}
stages:
  - name: only
    inputs:
      sample: "{sample_file}"
    steps:
      - {name: a, package: labUtils.x, method: run}
"""

BODY = b"plate,od600\nA1,0.42\n"


@pytest.fixture
def settings(tmp_path):
    return load_settings(
        artifact_root=tmp_path / "artifacts", workspace_root=tmp_path / "workspaces"
    )


@pytest.fixture
def store(settings) -> PosixArtifactStore:
    return PosixArtifactStore(settings.artifact_root)


@pytest.fixture
def user(db: Session) -> uuid.UUID:
    return db.execute(
        text(
            "INSERT INTO users (email, display_name, role) VALUES (:e, 'U', 'admin') RETURNING id"
        ),
        {"e": f"up-{uuid.uuid4().hex[:10]}@example.org"},
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


def an_upload(db: Session, user: uuid.UUID, store: PosixArtifactStore, settings, body=BODY):
    """A completed upload, by the same calls the HTTP layer makes."""
    upload = begin_upload(
        db, owner_id=user, filename="plate_01.csv", settings=settings, declared_size_bytes=len(body)
    )
    staging = store.path_for(staging_key(upload.id))
    staging.parent.mkdir(parents=True, exist_ok=True)
    staging.write_bytes(body)
    upload.received_bytes = len(body)
    db.flush()
    complete_upload(db, upload, store=store, settings=settings)
    return upload


def a_run(db: Session, user: uuid.UUID, reference: str):
    revision = create_revision(
        db, source_text=DOC.replace("__NAME__", f"si_{uuid.uuid4().hex[:8]}"), owner_id=user
    )
    return submit_run(
        db,
        pipeline_revision_id=revision.revision_id,
        requested_by=user,
        values={"sample_file": reference},
    )


def test_the_file_lands_where_the_task_was_told_to_look(db: Session, user, store, settings):
    upload = an_upload(db, user, store, settings)
    submitted = a_run(db, user, f"upload:{upload.id}")
    workspace = create_workspace(settings.workspace_root, submitted.run_id)

    placed = stage_inputs(
        staged_inputs_for_run(db, submitted.run_id),
        session=db,
        root=workspace.root,
        store=store,
    )
    assert placed == [f"inputs/{upload.id}/plate_01.csv"]

    spec = db.execute(
        text("SELECT task_spec FROM run_tasks WHERE run_id = :r"), {"r": submitted.run_id}
    ).scalar_one()
    # The path in the spec and the path on disk are the same string, which is
    # the only thing keeping the container from reporting a missing file.
    assert (workspace.root / spec["inputs"]["sample"]).read_bytes() == BODY


def test_the_bytes_are_shared_rather_than_copied(db: Session, user, store, settings):
    upload = an_upload(db, user, store, settings)
    submitted = a_run(db, user, f"upload:{upload.id}")
    workspace = create_workspace(settings.workspace_root, submitted.run_id)
    plan = staged_inputs_for_run(db, submitted.run_id)
    stage_inputs(plan, session=db, root=workspace.root, store=store)

    staged = workspace.root / plan[0].path
    original = store.path_for(
        db.execute(
            text("SELECT storage_key FROM artifacts WHERE id = :i"), {"i": plan[0].artifact_id}
        ).scalar_one()
    )
    # A hardlink, not a second copy: tens of gigabytes per run otherwise, for
    # a file the platform already has and will not modify.
    assert staged.stat().st_ino == original.stat().st_ino


def test_staging_twice_does_nothing_the_second_time(db: Session, user, store, settings):
    """Every task and every retry in a run calls this, not just the first."""
    upload = an_upload(db, user, store, settings)
    submitted = a_run(db, user, f"upload:{upload.id}")
    workspace = create_workspace(settings.workspace_root, submitted.run_id)
    plan = staged_inputs_for_run(db, submitted.run_id)

    assert stage_inputs(plan, session=db, root=workspace.root, store=store)
    assert stage_inputs(plan, session=db, root=workspace.root, store=store) == []
    assert (workspace.root / plan[0].path).read_bytes() == BODY


def test_a_vanished_input_fails_the_task_rather_than_the_worker(
    db: Session, user, store, settings, worker_id
):
    """Retention can take an input between submission and execution.

    The worker has to record that as a failed task with a reason. Raising out
    of the executor would take down every other task queued behind it, which
    is how one expired upload becomes an outage.
    """
    upload = an_upload(db, user, store, settings)
    submitted = a_run(db, user, f"upload:{upload.id}")
    task_id = db.execute(
        text("SELECT id FROM run_tasks WHERE run_id = :r"), {"r": submitted.run_id}
    ).scalar_one()
    store.delete(
        db.execute(
            text("SELECT storage_key FROM artifacts WHERE id = :i"), {"i": upload.artifact_id}
        ).scalar_one()
    )

    workspace = create_workspace(settings.workspace_root, submitted.run_id)
    outcome = execute_task(
        db,
        task_id=task_id,
        run_id=submitted.run_id,
        task_spec={"steps": [{"name": "a", "package": "labUtils.x", "method": "run"}]},
        stage_key="only",
        task_key="only",
        attempt=1,
        workspace=workspace,
        adapter=DockerAdapter(image="never-launched"),
        limits=ResourceLimits(cpu_millicores=1000, memory_bytes=1024**3, wall_time_seconds=60),
        image_ref="img:dev",
        worker_id=worker_id,
        store=store,
    )
    assert not outcome.succeeded
    assert "plate_01.csv" in (outcome.reason or "")


def test_a_purged_upload_cannot_be_submitted_at_all(db: Session, user, store, settings):
    """The earlier of the two refusals: at the form, not at the container."""
    upload = an_upload(db, user, store, settings)
    db.execute(
        text("UPDATE artifacts SET purged_at = now(), deleted_at = now() WHERE id = :i"),
        {"i": upload.artifact_id},
    )
    with pytest.raises(SubmissionRejected) as refused:
        a_run(db, user, f"upload:{upload.id}")
    assert "Upload it again" in refused.value.diagnostics[0].message


def test_a_run_with_no_uploads_stages_nothing(db: Session, user, store, settings):
    upload = an_upload(db, user, store, settings)
    submitted = a_run(db, user, f"upload:{upload.id}")
    assert len(staged_inputs_for_run(db, submitted.run_id)) == 1
    assert staged_inputs_for_run(db, uuid.uuid4()) == []


def test_staging_reports_which_file_is_missing(db: Session, user, store, settings):
    upload = an_upload(db, user, store, settings)
    submitted = a_run(db, user, f"upload:{upload.id}")
    plan = staged_inputs_for_run(db, submitted.run_id)
    db.execute(text("DELETE FROM uploads WHERE id = :i"), {"i": upload.id})
    db.execute(text("DELETE FROM artifacts WHERE id = :i"), {"i": upload.artifact_id})
    db.flush()

    workspace = create_workspace(settings.workspace_root, submitted.run_id)
    with pytest.raises(UploadRejected) as error:
        stage_inputs(plan, session=db, root=workspace.root, store=store)
    assert str(upload.id) in error.value.message
