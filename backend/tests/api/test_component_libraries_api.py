"""Author component libraries and compile pipelines against retained versions."""

from __future__ import annotations

import uuid

import pytest

from app.api.main import create_app
from app.settings import load_settings

pytestmark = pytest.mark.db

SOURCE = """graphs:
  convert:
    - name: result
      package: builtins
      method: str
      parameters:
        object: hello
"""


@pytest.fixture
def app(engine, tmp_path):
    settings = load_settings(
        artifact_root=tmp_path / "artifacts",
        workspace_root=tmp_path / "workspaces",
        component_library_root=tmp_path / "components",
        secure_cookies=False,
    )
    return create_app(settings=settings, engine=engine)


def test_create_edit_read_history_and_compile_saved_component(as_admin):
    assert as_admin.get("/api/v1/components").json() == []
    valid = as_admin.post("/api/v1/components/validate", json={"source_text": SOURCE})
    assert valid.json() == {"ok": True, "graphs": ["convert"], "message": None}
    first = as_admin.post(
        "/api/v1/components/revisions",
        json={
            "name": "convert.yaml",
            "source_text": SOURCE,
        },
    )
    assert first.status_code == 201, first.text
    initial = first.json()
    changed = SOURCE.replace("hello", "changed")
    second = as_admin.post(
        "/api/v1/components/revisions",
        json={
            "name": "convert.yaml",
            "source_text": changed,
            "expected_digest": initial["digest"],
        },
    )
    assert second.status_code == 201, second.text
    assert (
        as_admin.get(
            "/api/v1/components/source",
            params={
                "name": "convert.yaml",
                "revision": initial["digest"],
            },
        ).json()["source_text"]
        == SOURCE
    )
    assert (
        len(as_admin.get("/api/v1/components/revisions", params={"name": "convert.yaml"}).json())
        == 2
    )
    document = f"""pipeline: component_{uuid.uuid4().hex[:8]}
components:
  selected:
    library: {initial["reference"]}
    graph: convert
stages:
  - name: process
    uses: selected
"""
    created = as_admin.post("/api/v1/pipelines/revisions", json={"source_text": document})
    assert created.status_code == 201, created.text
    preview = as_admin.post("/api/v1/pipelines/compile-preview", json={"source_text": document})
    assert preview.json()["graph_hash"] == created.json()["graph_hash"]
    current = as_admin.post(
        "/api/v1/pipelines/compile-preview",
        json={"source_text": document.replace(initial["reference"], "convert.yaml")},
    )
    assert current.json()["ok"]
    assert current.json()["graph_hash"] != created.json()["graph_hash"]


def test_reject_stale_edit_and_invalid_source(as_admin):
    created = as_admin.post(
        "/api/v1/components/revisions", json={"name": "one.yaml", "source_text": SOURCE}
    )
    assert created.status_code == 201
    stale = as_admin.post(
        "/api/v1/components/revisions", json={"name": "one.yaml", "source_text": SOURCE}
    )
    assert stale.status_code == 409
    bad = as_admin.post("/api/v1/components/validate", json={"source_text": "graphs: {empty: []}"})
    assert not bad.json()["ok"]
    refused = as_admin.post(
        "/api/v1/components/revisions",
        json={"name": "bad.yaml", "source_text": "graphs: {empty: []}"},
    )
    assert refused.status_code == 422


def test_component_sources_are_admin_only(as_researcher, api):
    for client, status in [(as_researcher, 403), (api, 401)]:
        assert client.get("/api/v1/components").status_code == status
        assert (
            client.get("/api/v1/components/source", params={"name": "one.yaml"}).status_code
            == status
        )
        assert (
            client.get("/api/v1/components/revisions", params={"name": "one.yaml"}).status_code
            == status
        )
        assert (
            client.post("/api/v1/components/validate", json={"source_text": SOURCE}).status_code
            == status
        )
        assert (
            client.post(
                "/api/v1/components/revisions", json={"name": "one.yaml", "source_text": SOURCE}
            ).status_code
            == status
        )


def test_missing_and_escaping_component_paths(as_admin):
    assert (
        as_admin.get("/api/v1/components/source", params={"name": "missing.yaml"}).status_code
        == 404
    )
    assert (
        as_admin.get("/api/v1/components/source", params={"name": "../outside.yaml"}).status_code
        == 422
    )
