"""Prepare, retrieve and authorize background result ZIP files."""

import io
import uuid
import zipfile

import pytest
from backend.tests.api.test_artifact_download import store_artifact
from sqlalchemy import text

from app.application.bundles import process_bundle
from app.infrastructure.artifacts import PosixArtifactStore
from app.workers.courier import Courier

pytestmark = pytest.mark.db


@pytest.fixture
def owned_run(as_admin, sessions, request):
    source = f"""pipeline: bundle_{uuid.uuid4().hex[:8]}
stages:
  - name: result
    steps:
      - {{name: value, package: builtins, method: str, parameters: {{object: hello}}}}
"""
    revision = as_admin.post("/api/v1/pipelines/revisions", json={"source_text": source})
    assert revision.status_code == 201, revision.text
    slug = f"bundle-{uuid.uuid4().hex[:8]}"
    publication = as_admin.post(
        "/api/v1/publications/revisions",
        json={
            "slug": slug,
            "title": "Bundle demo",
            "pipeline_revision_id": revision.json()["revision_id"],
            "fields": [],
            "display_metadata": {
                "result_delivery": getattr(request, "param", ["individual", "zip"])
            },
        },
    )
    assert publication.status_code == 201, publication.text
    body = publication.json()
    assert (
        as_admin.post(
            f"/api/v1/publications/{body['publication_id']}/publish",
            params={"revision_id": body["revision_id"]},
        ).status_code
        == 200
    )
    created = as_admin.post(f"/api/v1/catalog/{slug}/runs", json={"values": {}})
    assert created.status_code == 201, created.text
    run_id = created.json()["run_id"]
    with sessions() as session:
        session.execute(text("UPDATE runs SET status = 'succeeded' WHERE id = :id"), {"id": run_id})
        session.commit()
    return run_id


def queue(client, run_id, ids=None):
    return client.post(f"/api/v1/runs/{run_id}/bundles", json={"artifact_ids": ids})


def process(app, sessions, job):
    with sessions() as session:
        return process_bundle(
            session,
            uuid.UUID(job["id"]),
            store=PosixArtifactStore(app.state.settings.artifact_root),
            settings=app.state.settings,
        )


def test_background_zip_contains_nested_files_and_is_reused(as_admin, owned_run, app, sessions):
    store_artifact(
        app, owned_run, filename="results", tree={"nested/a.txt": b"alpha", "empty.txt": b""}
    )
    requested = queue(as_admin, owned_run)
    assert requested.status_code == 201, requested.text
    job = requested.json()
    assert job["status"] == "pending"
    report = Courier(app.state.engine, app.state.settings).round()
    assert report.bundles_processed == 1
    status = as_admin.get(f"/api/v1/runs/{owned_run}/bundles/{job['id']}").json()
    assert status["status"] == "ready", status
    assert status["completed_bytes"] == status["total_bytes"] == 5
    response = as_admin.get(f"/api/v1/artifacts/{status['artifact_id']}/download")
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        first = next(name for name in archive.namelist() if name.endswith("nested/a.txt"))
        assert archive.read(first) == b"alpha"
        assert any(name.endswith("empty.txt") for name in archive.namelist())
    again = queue(as_admin, owned_run)
    assert again.json()["id"] == job["id"]
    assert again.json()["artifact_id"] == status["artifact_id"]
    assert process(app, sessions, again.json()) is False


def test_empty_directory_is_kept_in_the_zip(as_admin, owned_run, app, sessions):
    output = store_artifact(app, owned_run, filename="empty", tree={})
    with sessions() as session:
        key = session.execute(
            text("SELECT storage_key FROM artifacts WHERE id = :id"), {"id": output}
        ).scalar_one()
    PosixArtifactStore(app.state.settings.artifact_root).path_for(key).mkdir(parents=True)
    job = queue(as_admin, owned_run).json()
    process(app, sessions, job)
    status = as_admin.get(f"/api/v1/runs/{owned_run}/bundles/{job['id']}").json()
    assert status["status"] == "ready", status
    with zipfile.ZipFile(
        io.BytesIO(as_admin.get(f"/api/v1/artifacts/{status['artifact_id']}/download").content)
    ) as archive:
        assert len(archive.namelist()) == 1 and archive.namelist()[0].endswith("/")


def test_another_users_run_and_zip_are_not_visible(
    as_admin, as_researcher, owned_run, app, sessions
):
    store_artifact(app, owned_run, filename="result.txt", body=b"private")
    job = queue(as_admin, owned_run).json()
    process(app, sessions, job)
    status = as_admin.get(f"/api/v1/runs/{owned_run}/bundles/{job['id']}").json()
    assert queue(as_researcher, owned_run).status_code == 404
    assert as_researcher.get(f"/api/v1/runs/{owned_run}/bundles/{job['id']}").status_code == 404
    assert (
        as_researcher.get(f"/api/v1/artifacts/{status['artifact_id']}/download").status_code == 404
    )


@pytest.mark.parametrize("owned_run", [["zip"], ["individual"]], indirect=True)
def test_publication_delivery_choices_are_enforced_on_the_server(as_admin, owned_run, app):
    output = store_artifact(app, owned_run, filename="result.txt", body=b"content")
    modes = as_admin.get(f"/api/v1/runs/{owned_run}").json()["result_delivery"]
    assert as_admin.get(f"/api/v1/artifacts/{output}/download").status_code == (
        200 if "individual" in modes else 422
    )
    assert queue(as_admin, owned_run).status_code == (201 if "zip" in modes else 422)


def test_failed_preparation_cleans_partial_zip_and_can_be_retried(
    as_admin, owned_run, app, sessions
):
    output = store_artifact(app, owned_run, filename="result.txt", body=b"content")
    job = queue(as_admin, owned_run).json()
    with sessions() as session:
        key = session.execute(
            text("SELECT storage_key FROM artifacts WHERE id = :id"), {"id": output}
        ).scalar_one()
    path = PosixArtifactStore(app.state.settings.artifact_root).path_for(key)
    path.unlink()
    process(app, sessions, job)
    failed = as_admin.get(f"/api/v1/runs/{owned_run}/bundles/{job['id']}").json()
    assert failed["status"] == "failed"
    assert not list(app.state.settings.artifact_root.rglob("*.partial"))
    path.write_bytes(b"content")
    retried = queue(as_admin, owned_run).json()
    assert retried["status"] == "pending" and retried["id"] == job["id"]
    process(app, sessions, retried)
    assert as_admin.get(f"/api/v1/runs/{owned_run}/bundles/{job['id']}").json()["status"] == "ready"


def test_size_limits_and_foreign_artifact_selection_are_refused(as_admin, owned_run, app):
    store_artifact(app, owned_run, filename="large.txt", body=b"1234")
    original = app.state.settings
    app.state.settings = original.model_copy(update={"output_bundle_max_bytes": 1})
    assert queue(as_admin, owned_run).status_code == 413
    app.state.settings = original
    assert queue(as_admin, owned_run, [str(uuid.uuid4())]).status_code == 422
