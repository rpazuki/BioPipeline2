"""Audit retention, cleanup recovery, and administrator-only resource deletion."""

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from app.application.deletions import process_deletions
from app.infrastructure.db.models import Artifact, ResourceDeletion, Run, RunTask, Upload, User

pytestmark = pytest.mark.db


def pipeline(client):
    response = client.post(
        "/api/v1/pipelines/revisions",
        json={
            "source_text": f"pipeline: delete_{uuid.uuid4().hex[:10]}\nstages:\n"
            "  - name: convert\n    steps:\n"
            "      - {name: result, package: builtins, method: str}\n"
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def stopped_run(client, sessions, revision):
    response = client.post(
        "/api/v1/runs", json={"pipeline_revision_id": revision["revision_id"], "values": {}}
    )
    assert response.status_code == 201, response.text
    identifier = uuid.UUID(response.json()["run_id"])
    with sessions() as session:
        run = session.get(Run, identifier)
        run.status = "failed"
        for task in session.scalars(select(RunTask).where(RunTask.run_id == identifier)):
            task.status = "failed"
        session.commit()
    return identifier


def cleanup(sessions, app):
    with sessions() as session:
        process_deletions(session, app.state.settings)
        session.commit()


def test_run_lifecycle_and_deletion_survive_file_cleanup(as_admin, sessions, app):
    revision = pipeline(as_admin)
    identifier = stopped_run(as_admin, sessions, revision)
    settings = app.state.settings
    workspace = Path(settings.workspace_root) / str(identifier)
    workspace.mkdir()
    (workspace / "private.log").write_text("log")
    other = Path(settings.workspace_root) / "other-run"
    other.mkdir()
    (other / "keep.csv").write_text("keep")
    with sessions() as session:
        run = session.get(Run, identifier)
        artifact = Artifact(
            project_id=run.project_id,
            run_id=identifier,
            owner_id=run.requested_by,
            kind="task_output",
            storage_key=f"runs/{identifier}/output",
            filename="output",
            size_bytes=4,
        )
        session.add(artifact)
        session.commit()
    output = Path(settings.artifact_root) / f"runs/{identifier}/output"
    output.parent.mkdir(parents=True)
    output.write_text("data")
    response = as_admin.delete(f"/api/v1/runs/{identifier}")
    assert response.status_code == 202, response.text
    assert as_admin.get(f"/api/v1/runs/{identifier}").status_code == 404
    cleanup(sessions, app)
    assert not workspace.exists() and not output.exists()
    assert (other / "keep.csv").read_text() == "keep"
    events = as_admin.get(
        "/api/v1/admin/audit-events", params={"target_id": str(identifier)}
    ).json()["items"]
    assert {item["action"] for item in events} >= {
        "run.submitted",
        "run.status_changed",
        "run.deletion_requested",
        "run.deleted",
    }
    assert all(item["target_id"] == str(identifier) for item in events)
    assert as_admin.delete(f"/api/v1/runs/{identifier}").json()["status"] == "complete"


def test_deletion_retains_requester_identity_after_cleanup_and_account_rename(
    as_admin,
    admin,
    sessions,
    app,
):
    identifier = stopped_run(as_admin, sessions, pipeline(as_admin))
    response = as_admin.delete(f"/api/v1/runs/{identifier}")
    assert response.status_code == 202, response.text
    job_id = response.json()["deletion_id"]
    cleanup(sessions, app)
    with sessions() as session:
        user = session.get(User, admin[0])
        user.display_name = "Updated administrator name"
        user.email = f"renamed-{uuid.uuid4().hex}@example.org"
        session.commit()
    listed = as_admin.get("/api/v1/admin/deletions")
    assert listed.status_code == 200, listed.text
    row = next(item for item in listed.json()["items"] if item["id"] == job_id)
    assert row["status"] == "complete"
    assert row["requested_by"] == str(admin[0])
    assert row["requested_by_name"] == "Admin"
    assert row["requested_by_email"] == admin[1]
    events = as_admin.get(
        "/api/v1/admin/audit-events", params={"target_id": str(identifier)}
    ).json()["items"]
    event = next(item for item in events if item["action"] == "run.deletion_requested")
    assert event["details"]["deletion_requested_by"]["email"] == admin[1]


def test_older_deletion_requests_still_show_their_retained_account(as_admin, admin, sessions):
    identifier = stopped_run(as_admin, sessions, pipeline(as_admin))
    response = as_admin.delete(f"/api/v1/runs/{identifier}")
    job_id = response.json()["deletion_id"]
    with sessions() as session:
        job = session.get(ResourceDeletion, uuid.UUID(job_id))
        job.details = {
            key: value for key, value in job.details.items() if key != "deletion_requested_by"
        }
        session.commit()
    rows = as_admin.get("/api/v1/admin/deletions").json()["items"]
    row = next(item for item in rows if item["id"] == job_id)
    assert row["requested_by"] == str(admin[0])
    assert row["requested_by_name"] == "Admin"
    assert row["requested_by_email"] == admin[1]


def test_cleanup_failure_is_recorded_and_retryable(as_admin, sessions, app, monkeypatch):
    identifier = stopped_run(as_admin, sessions, pipeline(as_admin))
    response = as_admin.delete(f"/api/v1/runs/{identifier}")
    job_id = response.json()["deletion_id"]

    def denied(*args, **kwargs):
        raise PermissionError("Test storage is unavailable")

    monkeypatch.setattr("app.application.deletions.remove_within", denied)
    cleanup(sessions, app)
    with sessions() as session:
        job = session.get(ResourceDeletion, uuid.UUID(job_id))
        assert job.status == "failed"
        assert "unavailable" in job.error
    monkeypatch.undo()
    assert as_admin.post(f"/api/v1/admin/deletions/{job_id}/retry").status_code == 202
    cleanup(sessions, app)
    events = as_admin.get(
        "/api/v1/admin/audit-events", params={"target_id": str(identifier)}
    ).json()["items"]
    assert {event["action"] for event in events} >= {"run.deletion_failed", "run.deleted"}


def test_active_run_deletion_is_refused(as_admin, sessions):
    revision = pipeline(as_admin)
    identifier = as_admin.post(
        "/api/v1/runs", json={"pipeline_revision_id": revision["revision_id"], "values": {}}
    ).json()["run_id"]
    assert as_admin.delete(f"/api/v1/runs/{identifier}").status_code == 409


def test_symlink_created_after_request_is_not_followed(as_admin, sessions, app):
    identifier = stopped_run(as_admin, sessions, pipeline(as_admin))
    job_id = as_admin.delete(f"/api/v1/runs/{identifier}").json()["deletion_id"]
    root = Path(app.state.settings.workspace_root)
    other = root / "keep"
    other.mkdir()
    (other / "data.csv").write_text("keep")
    (root / str(identifier)).symlink_to(other, target_is_directory=True)
    cleanup(sessions, app)
    assert (other / "data.csv").read_text() == "keep"
    with sessions() as session:
        assert session.get(ResourceDeletion, uuid.UUID(job_id)).status == "failed"


def test_shared_upload_is_kept_until_last_run_is_deleted(as_admin, sessions, app):
    revision = pipeline(as_admin)
    first = stopped_run(as_admin, sessions, revision)
    second = stopped_run(as_admin, sessions, revision)
    upload_id = uuid.uuid4()
    key = f"uploads/{upload_id}/input.csv"
    path = Path(app.state.settings.artifact_root) / key
    path.parent.mkdir(parents=True)
    path.write_text("data")
    with sessions() as session:
        run = session.get(Run, first)
        artifact = Artifact(
            project_id=run.project_id,
            owner_id=run.requested_by,
            kind="upload_input",
            storage_key=key,
            filename="input.csv",
            size_bytes=4,
        )
        session.add(artifact)
        session.flush()
        session.add(
            Upload(
                id=upload_id,
                project_id=run.project_id,
                owner_id=run.requested_by,
                filename="input.csv",
                storage_key=f"uploads/staging/{upload_id}",
                status="completed",
                artifact_id=artifact.id,
                received_bytes=4,
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
        )
        for run_id in [first, second]:
            row = session.get(Run, run_id)
            row.compiled_run_spec = {
                "staged_inputs": [{"artifact_id": str(artifact.id), "path": "inputs/input.csv"}]
            }
        session.commit()
    assert as_admin.delete(f"/api/v1/runs/{first}").status_code == 202
    cleanup(sessions, app)
    assert path.exists()
    assert as_admin.delete(f"/api/v1/runs/{second}").status_code == 202
    cleanup(sessions, app)
    assert not path.exists()


def test_definition_deletion_is_audited_and_versions_cannot_be_reused(as_admin, sessions):
    revision = pipeline(as_admin)
    identifier = stopped_run(as_admin, sessions, revision)
    version = revision["revision_id"]
    source = as_admin.get(f"/api/v1/pipelines/revisions/{version}").json()["source_text"]
    assert as_admin.delete(f"/api/v1/pipelines/revisions/{version}").status_code == 204
    assert as_admin.get(f"/api/v1/pipelines/revisions/{version}").status_code == 404
    assert (
        as_admin.post(
            "/api/v1/runs", json={"pipeline_revision_id": version, "values": {}}
        ).status_code
        != 201
    )
    assert as_admin.get(f"/api/v1/runs/{identifier}").status_code == 200
    events = as_admin.get("/api/v1/admin/audit-events", params={"target_id": version}).json()[
        "items"
    ]
    assert events[0]["action"] == "pipeline_revision.deleted"
    recreated = as_admin.post("/api/v1/pipelines/revisions", json={"source_text": source})
    assert recreated.status_code == 201
    assert recreated.json()["version"] == 2
    assert recreated.json()["revision_id"] != version


def test_publication_must_be_withdrawn_before_audited_deletion(as_admin):
    revision = pipeline(as_admin)
    created = as_admin.post(
        "/api/v1/publications/revisions",
        json={
            "slug": f"delete-{uuid.uuid4().hex[:10]}",
            "title": "Delete example",
            "pipeline_revision_id": revision["revision_id"],
            "fields": [],
        },
    )
    assert created.status_code == 201, created.text
    publication = created.json()["publication_id"]
    publication_revision = created.json()["revision_id"]
    assert (
        as_admin.post(
            f"/api/v1/publications/{publication}/publish",
            params={"revision_id": publication_revision},
        ).status_code
        == 200
    )
    assert as_admin.delete(f"/api/v1/publications/{publication}").status_code == 409
    assert (
        as_admin.delete(f"/api/v1/pipelines/revisions/{revision['revision_id']}").status_code == 409
    )
    assert as_admin.post(f"/api/v1/publications/{publication}/archive").status_code == 200
    assert as_admin.delete(f"/api/v1/publications/{publication}").status_code == 204
    assert publication not in {
        item["id"] for item in as_admin.get("/api/v1/publications").json()["items"]
    }
    assert (
        as_admin.post(
            f"/api/v1/publications/{publication}/publish",
            params={"revision_id": publication_revision},
        ).status_code
        == 404
    )
    events = as_admin.get("/api/v1/admin/audit-events", params={"target_id": publication}).json()[
        "items"
    ]
    assert events[0]["action"] == "publication.deleted"


@pytest.mark.parametrize("confirmed", [True, False])
def test_delivered_outputs_and_zip_files_are_removed(as_admin, sessions, app, tmp_path, confirmed):
    from app.application.deliveries import destination_for
    from app.infrastructure.db.models import ArtifactBundle, RunDelivery, SharedStorageRoot

    identifier = stopped_run(as_admin, sessions, pipeline(as_admin))
    shared = tmp_path / "shared"
    shared.mkdir()
    bundle_id = uuid.uuid4()
    root_id = f"delete-{uuid.uuid4().hex[:8]}"
    with sessions() as session:
        run = session.get(Run, identifier)
        root = SharedStorageRoot(
            id=root_id,
            project_id=run.project_id,
            label="Test shared outputs",
            root_path=str(shared),
            readable=True,
            writable=True,
            attested_by=run.requested_by,
            attested_at=datetime.now(UTC),
        )
        session.add(root)
        artifact = Artifact(
            project_id=run.project_id,
            run_id=identifier,
            owner_id=run.requested_by,
            kind="task_output",
            storage_key=f"runs/{identifier}/result",
            filename="result.csv",
            size_bytes=4,
        )
        session.add(artifact)
        session.flush()
        delivery = RunDelivery(
            run_id=identifier,
            field_key="results",
            mode="shared",
            status="delivered" if confirmed else "failed",
            artifact_id=artifact.id,
            target_root_id=root_id,
        )
        session.add(delivery)
        target = destination_for(session, delivery, root, artifact)
        delivery.target_path = str(target) if confirmed else None
        session.add(
            ArtifactBundle(
                id=bundle_id,
                run_id=identifier,
                requested_by=run.requested_by,
                request_key=uuid.uuid4().hex,
                source_ids=[str(artifact.id)],
                status="pending",
            )
        )
        session.commit()
    target.parent.mkdir(parents=True)
    target.write_text("data")
    zip_path = Path(app.state.settings.artifact_root) / f"bundles/{bundle_id}/output.zip"
    zip_path.parent.mkdir(parents=True)
    zip_path.write_text("zip")
    keep = shared / "keep.csv"
    keep.write_text("keep")
    response = as_admin.delete(f"/api/v1/runs/{identifier}")
    if not confirmed:
        assert response.status_code == 409
        assert target.read_text() == "data"
        assert zip_path.exists()
        return
    assert response.status_code == 202
    cleanup(sessions, app)
    assert not target.exists() and not zip_path.exists()
    assert keep.read_text() == "keep"


def test_audit_and_cleanup_requests_are_administrator_only(as_researcher):
    assert as_researcher.get("/api/v1/admin/audit-events").status_code == 403
    assert as_researcher.get("/api/v1/admin/deletions").status_code == 403


def test_a_busy_zip_prevents_run_deletion(as_admin, sessions, app):
    from app.application.uploads import exclusive
    from app.infrastructure.db.models import ArtifactBundle

    identifier = stopped_run(as_admin, sessions, pipeline(as_admin))
    bundle_id = uuid.uuid4()
    with sessions() as session:
        run = session.get(Run, identifier)
        session.add(
            ArtifactBundle(
                id=bundle_id,
                run_id=identifier,
                requested_by=run.requested_by,
                request_key=uuid.uuid4().hex,
                source_ids=[],
                status="working",
            )
        )
        session.commit()
    path = Path(app.state.settings.artifact_root) / f"bundles/locks/{bundle_id}"
    with exclusive(path):
        response = as_admin.delete(f"/api/v1/runs/{identifier}")
    assert response.status_code == 409
    assert "ZIP" in response.json()["error"]["message"]
    assert as_admin.get(f"/api/v1/runs/{identifier}").status_code == 200


def test_changed_storage_root_does_not_clean_a_different_directory(as_admin, sessions, app):
    identifier = stopped_run(as_admin, sessions, pipeline(as_admin))
    job_id = as_admin.delete(f"/api/v1/runs/{identifier}").json()["deletion_id"]
    alternative = Path(app.state.settings.workspace_root) / "replacement"
    alternative.mkdir()
    target = alternative / str(identifier)
    target.mkdir()
    (target / "keep.csv").write_text("keep")
    settings = app.state.settings.model_copy(update={"workspace_root": alternative})
    with sessions() as session:
        process_deletions(session, settings)
        session.commit()
        assert session.get(ResourceDeletion, uuid.UUID(job_id)).status == "failed"
    assert (target / "keep.csv").read_text() == "keep"


def test_component_cleanup_refuses_a_changed_library_root(as_admin, sessions, app, tmp_path):
    from app.infrastructure.component_store import ComponentStore

    original_root = tmp_path / "original"
    other_root = tmp_path / "other"
    original = ComponentStore(original_root)
    other = ComponentStore(other_root)
    source = "graphs: {convert: [{name: result, package: builtins, method: str}]}"
    saved = original.save("example.yaml", source, None)
    other.save("example.yaml", source, None)
    app.state.settings = app.state.settings.model_copy(
        update={"component_library_root": original_root}
    )
    response = as_admin.delete(
        "/api/v1/components/source",
        params={"name": "example.yaml", "expected_digest": saved["digest"]},
    )
    assert response.status_code == 202
    settings = app.state.settings.model_copy(update={"component_library_root": other_root})
    with sessions() as session:
        process_deletions(session, settings)
        session.commit()
        job = session.get(ResourceDeletion, uuid.UUID(response.json()["deletion_id"]))
        assert job.status == "failed"
    assert original.read("example.yaml")["source_text"] == source
    assert other.read("example.yaml")["source_text"] == source


@pytest.mark.parametrize(
    "path",
    [
        "/runs/{id}",
        "/publications/{id}",
        "/pipelines/revisions/{id}",
        "/components/source?name=test.yaml&expected_digest=abc",
    ],
)
def test_researcher_cannot_delete_resources(as_researcher, path):
    assert as_researcher.delete("/api/v1" + path.format(id=uuid.uuid4())).status_code == 403
