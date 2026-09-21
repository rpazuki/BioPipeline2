"""The database against the disks it describes.

Phase 9's acceptance is a restore that reports zero orphans, but the two
halves of that check are not equally serious and the tests here keep them
apart. A row promising bytes that are gone is a broken download and a lie in
the audit trail. A directory nothing points at is disk, and a backup taken
database-first produces those on purpose.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.application.pipelines import create_revision
from app.application.reconcile import (
    ARTIFACT,
    GENERATION,
    MISSING,
    ORPHAN,
    UPLOAD,
    WORKSPACE,
    Finding,
    reclaim_orphans,
    reconcile,
)
from app.application.runs import submit_run

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
def roots(tmp_path) -> dict[str, Path]:
    made = {
        "artifact_root": tmp_path / "artifacts",
        "environment_root": tmp_path / "environments",
        "workspace_root": tmp_path / "workspaces",
    }
    for path in made.values():
        path.mkdir()
    return made


@pytest.fixture
def user(db: Session) -> uuid.UUID:
    return db.execute(
        text(
            "INSERT INTO users (email, display_name, role) VALUES (:e, 'R', 'admin') RETURNING id"
        ),
        {"e": f"rec-{uuid.uuid4().hex[:10]}@example.org"},
    ).scalar_one()


def a_run(db: Session, user: uuid.UUID) -> uuid.UUID:
    revision = create_revision(
        db, source_text=DOC.replace("__NAME__", f"rec_{uuid.uuid4().hex[:8]}"), owner_id=user
    )
    return submit_run(
        db, pipeline_revision_id=revision.revision_id, requested_by=user, values={}
    ).run_id


def an_artifact(db: Session, *, run_id: uuid.UUID | None, key: str) -> uuid.UUID:
    project = db.execute(text("SELECT id FROM projects WHERE is_default")).scalar_one()
    return db.execute(
        text(
            "INSERT INTO artifacts (project_id, run_id, kind, storage_key, filename, size_bytes) "
            "VALUES (:p, :r, 'task_output', :k, 'out.txt', 5) RETURNING id"
        ),
        {"p": project, "r": run_id, "k": key},
    ).scalar_one()


def written(root: Path, key: str, body: bytes = b"bytes") -> Path:
    path = root / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return path


def check(db: Session, roots: dict[str, Path]):
    return reconcile(db, **roots)


def only(result, *, kind: str, trouble: str) -> list[Finding]:
    return [item for item in result.findings if item.kind == kind and item.trouble == trouble]


# --- bytes a row promised --------------------------------------------------


def test_a_row_whose_bytes_are_gone_is_reported(db: Session, user, roots):
    """The failure that matters: somebody clicks a download and the platform,
    not the disk, is what let them down."""
    run_id = a_run(db, user)
    key = f"runs/{run_id}/only/attempt-1/out.txt"
    artifact_id = an_artifact(db, run_id=run_id, key=key)

    result = check(db, roots)

    missing = only(result, kind=ARTIFACT, trouble=MISSING)
    assert [item.reference for item in missing] == [str(artifact_id)]
    assert result.missing


def test_a_row_with_its_bytes_is_not_reported(db: Session, user, roots):
    run_id = a_run(db, user)
    key = f"runs/{run_id}/only/attempt-1/out.txt"
    an_artifact(db, run_id=run_id, key=key)
    written(roots["artifact_root"], key)

    result = check(db, roots)

    assert not result.missing
    assert not only(result, kind=ARTIFACT, trouble=ORPHAN)


def test_a_purged_row_is_not_expected_to_have_bytes(db: Session, user, roots):
    """`purged_at` is the record that deletion actually happened, so a row
    carrying one is the one case where absence is correct."""
    run_id = a_run(db, user)
    key = f"runs/{run_id}/only/attempt-1/out.txt"
    artifact_id = an_artifact(db, run_id=run_id, key=key)
    db.execute(
        text("UPDATE artifacts SET deleted_at = now(), purged_at = now() WHERE id = :i"),
        {"i": artifact_id},
    )

    assert not check(db, roots).missing


# --- disk nothing points at ------------------------------------------------


def test_a_run_directory_no_artifact_claims_is_waste(db: Session, roots):
    written(roots["artifact_root"], f"runs/{uuid.uuid4()}/only/attempt-1/out.txt", b"x" * 1024)

    orphans = only(check(db, roots), kind=ARTIFACT, trouble=ORPHAN)

    assert len(orphans) == 1
    assert orphans[0].size_bytes == 1024


def test_a_staging_file_for_an_upload_nobody_is_sending_is_waste(db: Session, roots):
    written(roots["artifact_root"], f"uploads/staging/{uuid.uuid4()}", b"half a bam")

    orphans = only(check(db, roots), kind=UPLOAD, trouble=ORPHAN)

    assert len(orphans) == 1
    assert "still being received" in orphans[0].detail


def test_a_staging_file_for_an_open_upload_is_left_alone(db: Session, user, roots):
    project = db.execute(text("SELECT id FROM projects WHERE is_default")).scalar_one()
    upload_id = db.execute(
        text(
            "INSERT INTO uploads (project_id, owner_id, filename, storage_key, received_bytes, "
            " expires_at) VALUES (:p, :u, 'big.bam', 'pending', 9, now() + interval '1 day') "
            "RETURNING id"
        ),
        {"p": project, "u": user},
    ).scalar_one()
    written(roots["artifact_root"], f"uploads/staging/{upload_id}", b"half a bam")

    assert not only(check(db, roots), kind=UPLOAD, trouble=ORPHAN)


def test_a_workspace_no_run_is_using_is_waste(db: Session, roots):
    written(roots["workspace_root"], f"{uuid.uuid4()}/outputs/result.csv", b"y" * 32)

    orphans = only(check(db, roots), kind=WORKSPACE, trouble=ORPHAN)

    assert len(orphans) == 1
    assert orphans[0].size_bytes == 32


def test_an_active_workspace_is_left_alone(db: Session, user, roots):
    run_id = a_run(db, user)
    db.execute(
        text("INSERT INTO workspaces (run_id, root_key, quota_bytes) VALUES (:r, :k, 1000)"),
        {"r": run_id, "k": str(run_id)},
    )
    written(roots["workspace_root"], f"{run_id}/outputs/result.csv")

    assert not only(check(db, roots), kind=WORKSPACE, trouble=ORPHAN)


# --- environment generations ----------------------------------------------


def a_generation(db: Session, roots, *, on_disk: bool = True, purged: bool = False):
    project = db.execute(text("SELECT id FROM projects WHERE is_default")).scalar_one()
    environment_id = db.execute(
        text(
            "INSERT INTO runtime_environments (project_id, name, venv_path, image_ref, status) "
            "VALUES (:p, :n, '', 'image:dev', 'available') RETURNING id"
        ),
        {"p": project, "n": f"rec-{uuid.uuid4().hex[:8]}"},
    ).scalar_one()
    generation_id = uuid.uuid4()
    path = roots["environment_root"] / str(environment_id) / str(generation_id)
    if on_disk:
        path.mkdir(parents=True)
        (path / "pyvenv.cfg").write_bytes(b"home = /usr/local/bin\n")
    db.execute(
        text(
            "INSERT INTO environment_generations (id, environment_id, digest, generation_path, "
            " status, built_at, purged_at) VALUES (:i, :e, :d, :path, 'ready', now(), "
            " CASE WHEN :purged THEN now() END)"
        ),
        {
            "i": generation_id,
            "e": environment_id,
            "d": "sha256:" + uuid.uuid4().hex + uuid.uuid4().hex,
            "path": str(path),
            "purged": purged,
        },
    )
    return generation_id, path


def test_a_generation_directory_no_row_points_at_is_waste(db: Session, roots):
    """What the janitor cannot see. It removes what rows name, so a directory
    left by a build that died before recording its path would sit there for
    ever."""
    stray = roots["environment_root"] / str(uuid.uuid4()) / str(uuid.uuid4())
    stray.mkdir(parents=True)
    (stray / "pyvenv.cfg").write_bytes(b"x" * 64)

    orphans = only(check(db, roots), kind=GENERATION, trouble=ORPHAN)

    assert len(orphans) == 1
    assert "no generation row points here" in orphans[0].detail


def test_a_generation_the_janitor_recorded_as_reclaimed_should_have_no_directory(
    db: Session, roots
):
    _generation_id, path = a_generation(db, roots, purged=True)

    orphans = only(check(db, roots), kind=GENERATION, trouble=ORPHAN)

    assert [item.path for item in orphans] == [str(path)]
    assert "already reclaimed" in orphans[0].detail


def test_a_live_generation_with_no_directory_is_missing(db: Session, roots):
    generation_id, _path = a_generation(db, roots, on_disk=False)

    missing = only(check(db, roots), kind=GENERATION, trouble=MISSING)

    assert [item.reference for item in missing] == [str(generation_id)]


def test_a_live_generation_on_disk_is_not_reported(db: Session, roots):
    a_generation(db, roots)

    result = check(db, roots)

    assert not only(result, kind=GENERATION, trouble=MISSING)
    assert not only(result, kind=GENERATION, trouble=ORPHAN)


# --- reclaiming ------------------------------------------------------------


def test_reclaiming_removes_the_waste_and_leaves_the_rows(db: Session, user, roots):
    """An operator freeing disk must not also be rewriting the record of what
    happened."""
    run_id = a_run(db, user)
    key = f"runs/{run_id}/only/attempt-1/out.txt"
    artifact_id = an_artifact(db, run_id=run_id, key=key)
    written(roots["artifact_root"], key)
    stray = written(roots["artifact_root"], f"runs/{uuid.uuid4()}/only/attempt-1/out.txt", b"z" * 8)

    result = check(db, roots)
    removed, freed, refused = reclaim_orphans(result.orphans, **roots)

    assert (removed, freed, refused) == (1, 8, ())
    assert not stray.parent.parent.exists()
    # The artifact that was fine is still fine, and its row never moved.
    assert (roots["artifact_root"] / key).is_file()
    assert db.execute(
        text("SELECT purged_at IS NULL FROM artifacts WHERE id = :i"), {"i": artifact_id}
    ).scalar_one()


def test_reclaiming_refuses_a_path_outside_its_root(tmp_path, roots):
    """The path comes out of a row, and a row can be wrong. Refusing is the
    only answer that cannot destroy something that was never ours."""
    elsewhere = tmp_path / "somebody-elses-data"
    elsewhere.mkdir()
    finding = Finding(
        kind=ARTIFACT,
        trouble=ORPHAN,
        reference="runs/forged",
        detail="pointed outside the root",
        path=str(elsewhere),
        size_bytes=1,
    )

    removed, freed, refused = reclaim_orphans([finding], **roots)

    assert (removed, freed) == (0, 0)
    assert refused == (str(elsewhere),)
    assert elsewhere.is_dir()


def test_a_clean_deployment_says_so(db: Session, user, roots):
    run_id = a_run(db, user)
    key = f"runs/{run_id}/only/attempt-1/out.txt"
    an_artifact(db, run_id=run_id, key=key)
    written(roots["artifact_root"], key)

    result = check(db, roots)

    assert not result.findings
    assert "nothing to report" in result.summary()
