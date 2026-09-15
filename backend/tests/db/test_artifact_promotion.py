"""Promotion: verified outputs become durable artifacts with deliveries."""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.application.artifacts import artifacts_for_run, promote_outputs
from app.application.pipelines import create_revision
from app.application.runs import submit_run
from app.infrastructure.artifacts import PosixArtifactStore
from app.infrastructure.workspace import collect_outputs, create_workspace

pytestmark = pytest.mark.db


DOC = """
pipeline: __NAME__
defaults: {root: /d}
stages:
  - name: only
    steps:
      - {name: a, package: labUtils.x, method: run}
    outputs:
      report:
        path: "outputs/report.txt"
        delivery: [download]
        retention_days: 30
      bundle:
        path: "outputs/bundle"
        delivery: [download, shared]
        shared_root: lab_results
"""


@pytest.fixture
def user(db: Session) -> uuid.UUID:
    return db.execute(
        text(
            "INSERT INTO users (email, display_name, role) VALUES (:e, 'A', 'admin') RETURNING id"
        ),
        {"e": f"a-{uuid.uuid4().hex[:10]}@example.org"},
    ).scalar_one()


@pytest.fixture
def store(tmp_path):
    return PosixArtifactStore(tmp_path / "artifacts")


@pytest.fixture
def promoted(db: Session, user, tmp_path, store):
    """A run whose single task produced both declared outputs."""
    revision = create_revision(
        db, source_text=DOC.replace("__NAME__", f"p_{uuid.uuid4().hex[:8]}"), owner_id=user
    )
    submitted = submit_run(
        db, pipeline_revision_id=revision.revision_id, requested_by=user, values={}
    )
    row = db.execute(
        text("SELECT id, task_key, task_spec FROM run_tasks WHERE run_id = :r"),
        {"r": submitted.run_id},
    ).one()
    attempt_id = db.execute(
        text(
            "INSERT INTO run_task_attempts (task_id, attempt_number, image_ref, status) "
            "VALUES (:t, 1, 'img', 'succeeded') RETURNING id"
        ),
        {"t": row.id},
    ).scalar_one()

    workspace = create_workspace(tmp_path / "ws", submitted.run_id)
    (workspace.outputs / "report.txt").write_text("results")
    bundle = workspace.outputs / "bundle"
    bundle.mkdir()
    (bundle / "a.csv").write_text("x,y\n1,2\n")
    (bundle / "b.csv").write_text("p,q\n3,4\n")

    declared = row.task_spec["outputs"]
    collected, missing = collect_outputs(workspace, declared)
    assert not missing

    result = promote_outputs(
        db,
        run_id=submitted.run_id,
        task_id=row.id,
        attempt_id=attempt_id,
        task_key=row.task_key,
        attempt=1,
        workspace=workspace,
        collected=collected,
        store=store,
        declared=declared,
    )
    return submitted.run_id, result


# --- artifacts ------------------------------------------------------------


def test_verified_outputs_become_artifacts(db: Session, promoted):
    _run_id, result = promoted
    assert len(result.artifacts) == 2
    keys = {artifact.key for artifact in result.artifacts}
    assert keys == {"report", "bundle"}


def test_an_artifact_records_its_checksum(db: Session, promoted, store):
    run_id, _ = promoted
    row = db.execute(
        text(
            "SELECT checksum_sha256, size_bytes FROM artifacts "
            "WHERE run_id = :r AND filename = 'report.txt'"
        ),
        {"r": run_id},
    ).one()
    assert row.checksum_sha256 is not None and len(row.checksum_sha256) == 64
    assert row.size_bytes == 7


def test_the_bytes_exist_before_the_row_does(db: Session, promoted, store):
    """An artifact row whose bytes are missing is a broken download and a lie
    in the audit trail."""
    _run_id, result = promoted
    for artifact in result.artifacts:
        assert store.exists(artifact.storage_key), artifact.key


def test_retention_is_taken_from_the_declaration(db: Session, promoted):
    run_id, _ = promoted
    expires = db.execute(
        text("SELECT expires_at FROM artifacts WHERE run_id = :r AND filename = 'report.txt'"),
        {"r": run_id},
    ).scalar_one()
    assert expires is not None


def test_artifacts_are_attributed_to_the_attempt_that_produced_them(db: Session, promoted):
    """A retry produces a second set; without this, which attempt wrote which
    bytes is unanswerable."""
    run_id, _ = promoted
    attributed = db.execute(
        text("SELECT count(*) FROM artifacts WHERE run_id = :r AND task_attempt_id IS NOT NULL"),
        {"r": run_id},
    ).scalar_one()
    assert attributed >= 2


# --- directories and manifests --------------------------------------------


def test_a_directory_output_gets_a_manifest(db: Session, promoted):
    _run_id, result = promoted
    assert len(result.manifests) == 1
    kind = db.execute(
        text("SELECT kind FROM artifacts WHERE id = :i"), {"i": result.manifests[0]}
    ).scalar_one()
    assert kind == "manifest"


def test_the_manifest_lists_the_files_with_checksums(db: Session, promoted, store):
    _run_id, result = promoted
    key = db.execute(
        text("SELECT storage_key FROM artifacts WHERE id = :i"),
        {"i": result.manifests[0]},
    ).scalar_one()
    payload = json.loads(store.path_for(key).read_text())
    assert payload["entry_count"] == 2
    assert {entry["path"] for entry in payload["entries"]} == {"a.csv", "b.csv"}
    assert all(len(entry["checksum_sha256"]) == 64 for entry in payload["entries"])


# --- deliveries -----------------------------------------------------------


def test_a_download_delivery_is_complete_on_creation(db: Session, promoted):
    """Nothing has to move: the artifact is retrievable as soon as it exists."""
    run_id, _ = promoted
    status = db.execute(
        text(
            "SELECT status FROM run_deliveries "
            "WHERE run_id = :r AND field_key = 'report' AND mode = 'download'"
        ),
        {"r": run_id},
    ).scalar_one()
    assert status == "delivered"


def test_a_shared_delivery_is_recorded_but_not_attempted(db: Session, promoted):
    """Writing institutional storage is blocked on ADR 0013. Recording the
    intent without acting on it keeps the run honest about what was not done,
    rather than silently dropping a declared destination."""
    run_id, _ = promoted
    row = db.execute(
        text("SELECT status, message FROM run_deliveries WHERE run_id = :r AND mode = 'shared'"),
        {"r": run_id},
    ).one()
    assert row.status == "pending"
    assert "ADR 0013" in row.message


def test_every_declared_mode_produces_a_delivery(db: Session, promoted):
    _run_id, result = promoted
    assert len(result.deliveries) == 3  # report: download; bundle: download + shared


# --- querying -------------------------------------------------------------


def test_a_run_lists_its_artifacts(db: Session, promoted):
    run_id, _ = promoted
    found = artifacts_for_run(db, run_id)
    assert len(found) == 3  # two outputs plus the manifest
    assert all(artifact.deleted_at is None for artifact in found)


def test_a_deleted_artifact_is_excluded(db: Session, promoted):
    run_id, result = promoted
    db.execute(
        text("UPDATE artifacts SET deleted_at = now() WHERE id = :i"),
        {"i": result.artifacts[0].artifact_id},
    )
    assert len(artifacts_for_run(db, run_id)) == 2
