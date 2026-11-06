"""Run attribution, historical catalogue names, search isolation, and measured storage."""

import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.application.run_storage import measure_files
from app.infrastructure.db.models import (
    Artifact,
    ArtifactBundle,
    Run,
    RunDelivery,
    SharedStorageRoot,
    User,
)

pytestmark = pytest.mark.db


@pytest.fixture
def revision(as_admin):
    response = as_admin.post(
        "/api/v1/pipelines/revisions",
        json={
            "source_text": f"pipeline: search_{uuid.uuid4().hex[:10]}\nstages:\n"
            "  - name: convert\n    steps:\n"
            "      - {name: result, package: builtins, method: str}\n"
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["revision_id"]


def submit(client, revision):
    response = client.post("/api/v1/runs", json={"pipeline_revision_id": revision, "values": {}})
    assert response.status_code == 201, response.text
    return response.json()["run_id"]


def test_run_user_and_empty_storage(as_admin, admin, revision):
    identifier = submit(as_admin, revision)
    detail = as_admin.get(f"/api/v1/runs/{identifier}").json()
    assert detail["requested_by_name"] == "Admin"
    assert detail["requested_by_email"] == admin[1]
    assert detail["catalogue_name"] is None
    assert detail["retained_storage_bytes"] == 0
    assert detail["storage_complete"] is True
    listed = as_admin.get("/api/v1/runs", params={"search": identifier}).json()
    assert listed["total"] == 1
    assert listed["items"][0]["requested_by_email"] == admin[1]


def test_search_uses_frozen_catalogue_and_respects_run_ownership(
    as_admin,
    as_researcher,
    researcher,
    revision,
    sessions,
):
    slug = f"run-search-{uuid.uuid4().hex[:8]}"

    def publish(title):
        response = as_admin.post(
            "/api/v1/publications/revisions",
            json={
                "slug": slug,
                "pipeline_revision_id": revision,
                "title": title,
                "fields": [],
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert (
            as_admin.post(
                f"/api/v1/publications/{body['publication_id']}/publish",
                params={"revision_id": body["revision_id"]},
            ).status_code
            == 200
        )

    publish("Original catalogue title")
    response = as_researcher.post(f"/api/v1/catalog/{slug}/runs", json={"values": {}})
    assert response.status_code == 201, response.text
    identifier = response.json()["run_id"]
    publish("Replacement catalogue title")
    admin_run = submit(as_admin, revision)
    with sessions() as session:
        session.get(User, researcher[0]).display_name = "Researcher 100%_unique"
        session.commit()
    for term in ("ORIGINAL CATALOGUE", slug, "100%_unique", researcher[1], identifier[:18]):
        body = as_admin.get("/api/v1/runs", params={"search": term}).json()
        assert identifier in {item["id"] for item in body["items"]}
    own = as_researcher.get("/api/v1/runs", params={"search": admin_run}).json()
    assert own["items"] == [] and own["total"] == 0
    assert as_researcher.get(f"/api/v1/runs/{admin_run}").status_code == 404
    assert (
        as_admin.get("/api/v1/runs", params={"search": "Replacement catalogue"}).json()["items"]
        == []
    )
    assert (
        as_admin.get(
            "/api/v1/runs", params={"search": identifier, "status_filter": "failed"}
        ).json()["total"]
        == 0
    )
    assert (
        as_admin.get(f"/api/v1/runs/{identifier}").json()["catalogue_name"]
        == "Original catalogue title"
    )


def test_run_search_pagination_and_deleted_runs(as_admin, revision, sessions):
    ids = [submit(as_admin, revision) for _ in range(3)]
    with sessions() as session:
        session.get(Run, uuid.UUID(ids[0])).deleted_at = datetime.now(UTC)
        session.commit()
    first = as_admin.get("/api/v1/runs", params={"limit": 1}).json()
    second = as_admin.get("/api/v1/runs", params={"limit": 1, "offset": 1}).json()
    assert first["total"] == second["total"] == 2
    assert first["items"][0]["id"] != second["items"][0]["id"]
    assert as_admin.get("/api/v1/runs", params={"search": ids[0]}).json()["total"] == 0
    assert as_admin.get("/api/v1/runs", params={"offset": -1}).status_code == 400


def test_storage_counts_existing_files_hardlinks_uploads_bundles_and_deliveries(
    as_admin,
    revision,
    sessions,
    app,
    tmp_path,
):
    identifier = uuid.UUID(submit(as_admin, revision))
    workspace = Path(app.state.settings.workspace_root) / str(identifier)
    workspace.mkdir()
    (workspace / "log").write_bytes(b"log")
    (workspace / "result").write_bytes(b"result")
    artifacts = Path(app.state.settings.artifact_root)
    output = artifacts / f"runs/{identifier}/result"
    output.parent.mkdir(parents=True)
    os.link(workspace / "result", output)
    source = artifacts / "uploads/source/data"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"input")
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "delivered").write_bytes(b"copy")
    (shared / "unrelated").write_bytes(b"not part of the run")
    bundle_id = uuid.uuid4()
    bundle = artifacts / f"bundles/{bundle_id}/output.zip"
    bundle.parent.mkdir(parents=True)
    bundle.write_bytes(b"zip")
    with sessions() as session:
        run = session.get(Run, identifier)
        uploaded = Artifact(
            project_id=run.project_id,
            owner_id=run.requested_by,
            kind="upload_input",
            storage_key="uploads/source/data",
            filename="data",
            size_bytes=999,
        )
        missing = Artifact(
            project_id=run.project_id,
            run_id=identifier,
            kind="task_output",
            storage_key="runs/missing",
            filename="missing",
            size_bytes=10000,
        )
        root = SharedStorageRoot(
            id=f"storage-{uuid.uuid4().hex[:8]}",
            project_id=run.project_id,
            label="Output storage",
            root_path=str(shared),
            writable=True,
            attested_by=run.requested_by,
            attested_at=datetime.now(UTC),
        )
        session.add_all([uploaded, missing, root])
        session.flush()
        run.compiled_run_spec = {
            **run.compiled_run_spec,
            "staged_inputs": [{"artifact_id": str(uploaded.id)}],
        }
        session.add(
            ArtifactBundle(
                id=bundle_id,
                run_id=identifier,
                requested_by=run.requested_by,
                request_key=uuid.uuid4().hex,
                source_ids=[],
                status="pending",
            )
        )
        session.add(
            RunDelivery(
                run_id=identifier,
                field_key="result",
                mode="shared",
                status="delivered",
                artifact_id=missing.id,
                target_root_id=root.id,
                target_path=str(shared / "delivered"),
            )
        )
        session.commit()
    response = as_admin.get(f"/api/v1/runs/{identifier}")
    assert response.status_code == 200, response.text
    assert response.json()["retained_storage_bytes"] == 3 + 6 + 5 + 4 + 3
    listed = as_admin.get("/api/v1/runs", params={"search": str(identifier)}).json()["items"][0]
    assert listed["retained_storage_bytes"] == response.json()["retained_storage_bytes"]


def test_measurement_refuses_links_escapes_and_reports_access_failure(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    (root / "file").write_bytes(b"data")
    outside = tmp_path / "other"
    outside.mkdir()
    (outside / "secret").write_bytes(b"unrelated")
    (root / "link").symlink_to(outside, target_is_directory=True)
    assert measure_files([(root, "file"), (root, "link")]) == (4, True)
    assert measure_files([(root, "..")]) == (0, False)
    original = Path.lstat

    def denied(path, *args, **kwargs):
        if path == root / "file":
            raise PermissionError("inaccessible")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", denied)
    assert measure_files([(root, "file")]) == (0, False)
