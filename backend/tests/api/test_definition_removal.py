import uuid

import pytest

from app.infrastructure.component_store import ComponentStore

pytestmark = pytest.mark.db


def test_archived_pipeline_leaves_the_active_list_but_retains_source_and_access_control(
    as_admin, as_researcher
):
    created = as_admin.post(
        "/api/v1/pipelines/revisions",
        json={
            "source_text": (
                f"pipeline: archive_{uuid.uuid4().hex[:8]}\nstages:\n"
                "  - name: convert\n    steps:\n"
                "      - {name: result, package: builtins, method: str}\n"
            )
        },
    )
    assert created.status_code == 201, created.text
    pipeline_id = created.json()["pipeline_id"]
    revision_id = created.json()["revision_id"]
    assert as_researcher.post(f"/api/v1/pipelines/{pipeline_id}/archive").status_code == 403
    for _ in range(2):
        assert as_admin.post(f"/api/v1/pipelines/{pipeline_id}/archive").status_code == 200
    assert pipeline_id not in [
        row["id"] for row in as_admin.get("/api/v1/pipelines").json()["items"]
    ]
    archived = as_admin.get("/api/v1/pipelines", params={"include_archived": True}).json()["items"]
    assert next(row for row in archived if row["id"] == pipeline_id)["status"] == "archived"
    assert as_admin.get(f"/api/v1/pipelines/revisions/{revision_id}").status_code == 200


def test_component_removal_checks_ownership_role_and_stale_digest_and_keeps_snapshot(
    as_admin, as_researcher, app, tmp_path
):
    app.state.settings = app.state.settings.model_copy(update={"component_library_root": tmp_path})
    store = ComponentStore(tmp_path)
    original = store.save(
        "example.yaml", "graphs: {convert: [{name: result, package: builtins, method: str}]}", None
    )
    path = "/api/v1/components/source"
    params = {"name": "example.yaml", "expected_digest": original["digest"]}
    assert as_researcher.delete(path, params=params).status_code == 403
    assert as_admin.delete(path, params={**params, "expected_digest": "0" * 64}).status_code == 409
    assert store.read("example.yaml")["digest"] == original["digest"]
    assert as_admin.delete(path, params=params).status_code == 204
    assert store.list() == []
    historical = as_admin.get(path, params={"name": "example.yaml", "revision": original["digest"]})
    assert historical.status_code == 200
    assert historical.json()["source_text"] == original["source_text"]
