"""Read saved sources and compile new revisions without changing publications."""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.db


@pytest.fixture
def source():
    return (
        f"# Preserve comments and whitespace\npipeline: source_{uuid.uuid4().hex[:8]}\n"
        "title: Source example\ndefaults:\n  n: 4\nstages:\n  - name: calculate\n"
        "    steps:\n      - name: convert\n        package: builtins\n"
        '        method: str\n        parameters:\n          object: "{n}"\n'
    )


def test_read_and_recompile_published_source_preserves_original(as_admin, source):
    first = as_admin.post("/api/v1/pipelines/revisions", json={"source_text": source})
    assert first.status_code == 201, first.text
    revision = first.json()
    publication = as_admin.post(
        "/api/v1/publications/revisions",
        json={
            "slug": f"source-{uuid.uuid4().hex[:8]}",
            "pipeline_revision_id": revision["revision_id"],
            "title": "Source test",
            "fields": [],
        },
    )
    assert publication.status_code == 201, publication.text
    published = publication.json()
    url = f"/api/v1/publications/{published['publication_id']}/publish"
    response = as_admin.post(url, params={"revision_id": published["revision_id"]})
    assert response.status_code == 200, response.text

    original_url = f"/api/v1/pipelines/revisions/{revision['revision_id']}"
    saved = as_admin.get(original_url)
    assert saved.status_code == 200
    assert saved.json()["source_text"] == source
    edited = saved.json()["source_text"].replace("n: 4", "n: 8")
    preview = as_admin.post("/api/v1/pipelines/compile-preview", json={"source_text": edited})
    assert preview.json()["ok"], preview.text
    created = as_admin.post("/api/v1/pipelines/revisions", json={"source_text": edited})
    assert created.status_code == 201, created.text
    assert created.json()["pipeline_id"] == revision["pipeline_id"]
    assert created.json()["revision_id"] != revision["revision_id"]
    assert created.json()["version"] == revision["version"] + 1
    assert as_admin.get(original_url).json() == saved.json()
    catalog = as_admin.get("/api/v1/publications").json()["items"]
    entry = next(item for item in catalog if item["id"] == published["publication_id"])
    assert entry["current_revision_id"] == published["revision_id"]


def test_source_is_admin_only(as_admin, as_researcher, api, source):
    created = as_admin.post("/api/v1/pipelines/revisions", json={"source_text": source}).json()
    url = f"/api/v1/pipelines/revisions/{created['revision_id']}"
    assert as_researcher.get(url).status_code == 403
    assert api.get(url).status_code == 401


def test_unknown_source_returns_not_found(as_admin):
    assert as_admin.get(f"/api/v1/pipelines/revisions/{uuid.uuid4()}").status_code == 404
