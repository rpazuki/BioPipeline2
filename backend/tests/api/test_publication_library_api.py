"""Author reusable presets and freeze them into publication revisions."""

import uuid

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.db

SOURCE = """definitions:
  Options:
    fields:
      window: {type: integer, required: true}
      enabled: {type: boolean, default: false}
  Choice:
    type: enum
    options:
      - {label: Standard, value: {window: 5, enabled: true}}
  Flag: {type: boolean}
presets:
  standard:
    type_ref: Options
    value: {window: '5'}
  disabled:
    type_ref: Flag
    value: false
"""

PIPELINE = """pipeline: __NAME__
defaults:
  config: $WILL_PROVIDE$
inputs:
  config: {accept: value}
stages:
  - name: process
    steps:
      - name: result
        package: builtins
        method: str
        parameters: {object: "{config}"}
"""


@pytest.fixture
def library(as_admin):
    original = as_admin.get("/api/v1/publication-library").json()
    response = as_admin.put(
        "/api/v1/publication-library",
        json={
            "source_text": SOURCE,
            "expected_digest": original["digest"],
        },
    )
    assert response.status_code == 200, response.text
    yield response.json()
    current = as_admin.get("/api/v1/publication-library").json()
    restored = as_admin.put(
        "/api/v1/publication-library",
        json={
            "source_text": original["source_text"],
            "expected_digest": current["digest"],
        },
    )
    assert restored.status_code == 200, restored.text


@pytest.fixture
def revision(as_admin):
    response = as_admin.post(
        "/api/v1/pipelines/revisions",
        json={
            "source_text": PIPELINE.replace("__NAME__", f"lib_{uuid.uuid4().hex[:10]}"),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["revision_id"]


def create(as_admin, revision, library, **overrides):
    field = {
        "key": "options",
        "label": "Processing options",
        "field_type": "object",
        "preset_ref": "standard",
        "binding": {"target": "default_value", "binding_key": "config"},
    }
    field.update(overrides)
    slug = f"lib-{uuid.uuid4().hex[:10]}"
    response = as_admin.post(
        "/api/v1/publications/revisions",
        json={
            "slug": slug,
            "title": "Library example",
            "pipeline_revision_id": revision,
            "library_digest": library["digest"],
            "fields": [field],
        },
    )
    return slug, response


def publish(as_admin, response):
    assert response.status_code == 201, response.text
    body = response.json()
    result = as_admin.post(
        f"/api/v1/publications/{body['publication_id']}/publish",
        params={"revision_id": body["revision_id"]},
    )
    assert result.status_code == 200, result.text


def test_library_requires_an_administrator(as_researcher, api):
    for client, code in [(as_researcher, 403), (api, 401)]:
        assert client.get("/api/v1/publication-library").status_code == code
        assert (
            client.post(
                "/api/v1/publication-library/validate", json={"source_text": SOURCE}
            ).status_code
            == code
        )

        assert (
            client.put(
                "/api/v1/publication-library",
                json={"source_text": SOURCE, "expected_digest": "0" * 64},
            ).status_code
            == code
        )


def test_legacy_import_is_a_preview_and_does_not_replace_the_saved_library(as_admin, library):
    imported = as_admin.post(
        "/api/v1/publication-library/import-preview",
        json={
            "source_text": "ImportedRate: {type: float}",
            "format": "legacy_types",
            "base_source": library["source_text"],
            "expected_digest": library["digest"],
        },
    )
    assert imported.status_code == 200, imported.text
    assert "ImportedRate" in imported.json()["source_text"]
    assert imported.json()["notes"]
    assert as_admin.get("/api/v1/publication-library").json()["digest"] == library["digest"]


def test_invalid_save_and_stale_edit_cannot_overwrite_library(as_admin, library):
    invalid = as_admin.put(
        "/api/v1/publication-library",
        json={
            "source_text": "presets: {x: {type_ref: Missing, value: 5}}",
            "expected_digest": library["digest"],
        },
    )
    assert invalid.status_code == 422
    stale = as_admin.put(
        "/api/v1/publication-library",
        json={
            "source_text": SOURCE + "\n",
            "expected_digest": "0" * 64,
        },
    )
    assert stale.status_code == 409
    assert as_admin.get("/api/v1/publication-library").json()["digest"] == library["digest"]


def test_publication_keeps_preset_and_schema_after_library_changes(
    as_admin,
    as_researcher,
    library,
    revision,
    sessions,
):
    slug, created = create(as_admin, revision, library)
    publish(as_admin, created)
    updated = as_admin.put(
        "/api/v1/publication-library",
        json={
            "source_text": "definitions: {}\npresets: {}\n",
            "expected_digest": library["digest"],
        },
    )
    assert updated.status_code == 200
    field = as_researcher.get(f"/api/v1/catalog/{slug}").json()["fields"][0]
    assert field["default_value"] == {"window": 5, "enabled": False}
    assert field["type_ref"] == "Options"
    run = as_researcher.post(f"/api/v1/catalog/{slug}/runs", json={"values": {}})
    assert run.status_code == 201, run.text
    with sessions() as session:
        task = session.execute(
            text("SELECT task_spec FROM run_tasks WHERE run_id = :id"), {"id": run.json()["run_id"]}
        ).scalar_one()
    assert task["steps"][0]["parameters"]["object"] == {"window": 5, "enabled": False}


def test_fixed_false_is_hidden_and_cannot_be_overridden(as_admin, as_researcher, library, revision):
    slug, created = create(
        as_admin,
        revision,
        library,
        preset_ref="disabled",
        field_type="boolean",
        visibility="hidden",
    )
    publish(as_admin, created)
    assert as_researcher.get(f"/api/v1/catalog/{slug}").json()["fields"] == []
    assert (
        as_researcher.post(f"/api/v1/catalog/{slug}/runs", json={"values": {}}).status_code == 201
    )
    # Schedules and repeated submissions can carry the already-resolved fixed value.
    assert (
        as_researcher.post(
            f"/api/v1/catalog/{slug}/runs", json={"values": {"options": False}}
        ).status_code
        == 201
    )
    refused = as_researcher.post(f"/api/v1/catalog/{slug}/runs", json={"values": {"options": True}})
    assert refused.status_code == 422
    assert "fixed" in refused.text


def test_selected_type_controls_researcher_values(as_admin, as_researcher, library, revision):
    slug, created = create(
        as_admin, revision, library, preset_ref=None, type_ref="Choice", field_type="enum"
    )
    publish(as_admin, created)
    good = as_researcher.post(
        f"/api/v1/catalog/{slug}/runs", json={"values": {"options": {"window": 5, "enabled": True}}}
    )
    assert good.status_code == 201, good.text
    bad = as_researcher.post(
        f"/api/v1/catalog/{slug}/runs", json={"values": {"options": {"window": 99}}}
    )
    assert bad.status_code == 422


def test_stale_library_selection_is_refused(as_admin, library, revision):
    _, response = create(as_admin, revision, {**library, "digest": "0" * 64})
    assert response.status_code == 409


def test_publication_cannot_replace_the_pipelines_declared_schema(as_admin, library):
    source = (
        PIPELINE.replace("__NAME__", f"typed_lib_{uuid.uuid4().hex[:10]}")
        .replace(
            "inputs:\n",
            "definitions:\n  Options:\n    fields:\n"
            "      window: {type: integer, required: true}\ninputs:\n",
        )
        .replace("config: {accept: value}", "config: {accept: value, type_ref: Options}")
    )
    compiled = as_admin.post("/api/v1/pipelines/revisions", json={"source_text": source})
    assert compiled.status_code == 201, compiled.text
    _, response = create(as_admin, compiled.json()["revision_id"], library)
    assert response.status_code == 422
    assert "preserve" in response.text


@pytest.mark.parametrize(
    "overrides",
    [
        {"preset_ref": "missing"},
        {
            "preset_ref": None,
            "type_ref": "Options",
            "fixed_value": {"window": "bad"},
            "visibility": "hidden",
        },
        {"default_value": {"window": 5}},
    ],
)
def test_bad_publication_values_are_rejected_before_storage(as_admin, library, revision, overrides):
    _, response = create(as_admin, revision, library, **overrides)
    assert response.status_code == 422, response.text
