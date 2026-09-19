"""Typed values end to end: declared, frozen, coerced, and kept.

A researcher fills in a four-field rule object, the platform turns `"200"`
into `200` before anything sees it, and they keep the whole thing under a name
so next week is one click. The type definition here is the real one, from the
deployment's own job definitions.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

pytestmark = pytest.mark.db

DOC = """
pipeline: __NAME__
title: Replicate aggregation
defaults:
  custom_rules: $WILL_PROVIDE$
  window: 5
definitions:
  CustomReplicateRule:
    description: Rule definition for custom replicate statistics aggregation.
    fields:
      direction:
        type: enum
        required: true
        options: [alphabetical, numerical]
      pattern: {type: string, required: false}
      sample_size: {type: integer, required: true}
inputs:
  custom_rules:
    accept: value
    type_ref: CustomReplicateRule
    help: How replicates are grouped.
stages:
  - name: fit
    steps:
      - name: a
        package: labUtils.demo
        method: run
        parameters: {rules: "{custom_rules}", n: "{window}"}
    outputs:
      report: {path: "outputs/report.txt"}
"""


@pytest.fixture
def revision(as_admin: TestClient) -> str:
    source = DOC.replace("__NAME__", f"typed_{uuid.uuid4().hex[:8]}")
    created = as_admin.post("/api/v1/pipelines/revisions", json={"source_text": source})
    assert created.status_code == 201, created.text
    return created.json()["revision_id"]


def rules_field(**overrides) -> dict:
    base = {
        "key": "rules",
        "label": "Replicate rule",
        "field_type": "object",
        "required": True,
        "type_ref": "CustomReplicateRule",
        "binding": {"target": "default_value", "binding_key": "custom_rules"},
    }
    base.update(overrides)
    return base


@pytest.fixture
def entry(as_admin: TestClient, revision: str) -> str:
    slug = f"typed-{uuid.uuid4().hex[:8]}"
    created = as_admin.post(
        "/api/v1/publications/revisions",
        json={
            "slug": slug,
            "pipeline_revision_id": revision,
            "title": "Replicate aggregation",
            "fields": [rules_field()],
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    opened = as_admin.post(
        f"/api/v1/publications/{body['publication_id']}/publish",
        params={"revision_id": body["revision_id"]},
    )
    assert opened.status_code == 200, opened.text
    return slug


GOOD = {"direction": "numerical", "pattern": "plate_", "sample_size": "200"}


# --- the type reaches the form ---------------------------------------------


def test_the_form_is_told_what_the_type_looks_like(as_researcher: TestClient, entry: str):
    """Without the schema the form can only offer a JSON box, which is what
    made a researcher type a five-key object by hand."""
    body = as_researcher.get(f"/api/v1/catalog/{entry}").json()
    field = body["fields"][0]

    assert field["type_ref"] == "CustomReplicateRule"
    schema = field["type_schema"]
    assert schema["kind"] == "struct"
    assert [entry_["name"] for entry_ in schema["fields"]] == [
        "direction",
        "pattern",
        "sample_size",
    ]
    assert schema["fields"][0]["options"][0]["value"] == "alphabetical"
    # Typed, so it is worth keeping. Nobody had to say so.
    assert field["saveable"] is True


def test_an_input_naming_a_type_nobody_defined_fails_the_compile(as_admin: TestClient):
    """The same rule bindings follow: a reference to something that does not
    exist is a mistake the author can still fix."""
    source = DOC.replace("__NAME__", f"typed_{uuid.uuid4().hex[:8]}").replace(
        "type_ref: CustomReplicateRule", "type_ref: NoSuchRule"
    )
    response = as_admin.post("/api/v1/pipelines/revisions", json={"source_text": source})

    assert response.status_code == 422
    codes = [item["code"] for item in response.json()["error"]["details"]["errors"]]
    assert "type.unresolved" in codes


# --- coercion at submit (G93) ----------------------------------------------


def test_the_string_becomes_a_number_before_anything_sees_it(
    as_researcher: TestClient, entry: str, engine: Engine
):
    response = as_researcher.post(f"/api/v1/catalog/{entry}/runs", json={"values": {"rules": GOOD}})
    assert response.status_code == 201, response.text

    with sessionmaker(bind=engine)() as session:
        spec = session.execute(
            text("SELECT task_spec FROM run_tasks WHERE run_id = :r"),
            {"r": response.json()["run_id"]},
        ).scalar_one()

    # The whole of G93: `"200"` reached a science function as a string.
    assert spec["steps"][0]["parameters"]["rules"]["sample_size"] == 200


def test_a_value_that_does_not_fit_is_refused_field_by_field(as_researcher: TestClient, entry: str):
    response = as_researcher.post(
        f"/api/v1/catalog/{entry}/runs",
        json={"values": {"rules": {"direction": "sideways", "sample_size": "many"}}},
    )

    assert response.status_code == 422
    problems = {
        item["path"]: item["message"] for item in response.json()["error"]["details"]["errors"]
    }
    assert "values.rules.direction" in problems
    assert "values.rules.sample_size" in problems
    assert "not a whole number" in problems["values.rules.sample_size"]


def test_the_published_type_does_not_change_under_a_running_entry(
    as_admin: TestClient, as_researcher: TestClient, entry: str, engine: Engine
):
    """A definition lives in a document, documents are superseded, and an entry
    published in March must go on asking for what it asked for in March."""
    with sessionmaker(bind=engine)() as session:
        frozen = session.execute(
            text(
                "SELECT type_schema FROM publication_fields f "
                "JOIN publication_revisions r ON r.id = f.publication_revision_id "
                "JOIN publications p ON p.id = r.publication_id WHERE p.slug = :s"
            ),
            {"s": entry},
        ).scalar_one()

    assert frozen["key"] == "CustomReplicateRule"
    assert len(frozen["fields"]) == 3


# --- saved values ----------------------------------------------------------


def saved_for(client: TestClient, entry: str, name: str = "Weekly plates", value=None):
    return client.post(
        "/api/v1/saved-values",
        params={"entry": entry},
        json={"field_key": "rules", "name": name, "value": value or GOOD},
    )


def test_a_filled_in_value_can_be_kept_and_comes_back_coerced(
    as_researcher: TestClient, entry: str
):
    created = saved_for(as_researcher, entry)
    assert created.status_code == 201, created.text
    assert created.json()["type_key"] == "CustomReplicateRule"
    # Stored as what it is, not as what the form sent.
    assert created.json()["value"]["sample_size"] == 200

    listed = as_researcher.get("/api/v1/saved-values", params={"type_key": "CustomReplicateRule"})
    assert [item["name"] for item in listed.json()["items"]] == ["Weekly plates"]


def test_a_saved_value_is_offered_only_where_it_fits(as_researcher: TestClient, entry: str):
    saved_for(as_researcher, entry)

    listed = as_researcher.get(
        "/api/v1/saved-values", params={"entry": entry, "field_key": "rules"}
    )

    assert listed.status_code == 200, listed.text
    assert listed.json()["items"][0]["usable"] is True
    assert listed.json()["items"][0]["unusable_reason"] is None


def test_a_saved_value_that_no_longer_fits_says_so_rather_than_being_offered(
    as_researcher: TestClient, entry: str, engine: Engine
):
    """The value's schema was frozen when it was saved and the field's when the
    entry was published. They can legitimately disagree."""
    created = saved_for(as_researcher, entry)
    with sessionmaker(bind=engine)() as session:
        session.execute(
            text(
                'UPDATE saved_values SET value = \'{"value": {"direction": "numerical"}}\' '
                "WHERE id = :i"
            ),
            {"i": created.json()["id"]},
        )
        session.commit()

    listed = as_researcher.get(
        "/api/v1/saved-values", params={"entry": entry, "field_key": "rules"}
    )
    item = listed.json()["items"][0]
    assert item["usable"] is False
    assert "sample_size" in item["unusable_reason"]


def test_a_value_that_does_not_match_its_type_is_never_saved(as_researcher: TestClient, entry: str):
    response = saved_for(as_researcher, entry, value={"direction": "sideways"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "value.invalid"


def test_two_saved_values_cannot_share_a_name(as_researcher: TestClient, entry: str):
    assert saved_for(as_researcher, entry).status_code == 201
    clash = saved_for(as_researcher, entry)
    assert clash.status_code == 409
    assert clash.json()["error"]["code"] == "saved_value.name_taken"


def test_a_saved_value_can_be_renamed_and_replaced(as_researcher: TestClient, entry: str):
    created = saved_for(as_researcher, entry)
    value_id = created.json()["id"]

    renamed = as_researcher.patch(
        f"/api/v1/saved-values/{value_id}",
        json={
            "name": "Monthly plates",
            "value": {**GOOD, "sample_size": 12},
            "replace_value": True,
        },
    )

    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "Monthly plates"
    assert renamed.json()["value"]["sample_size"] == 12


def test_a_saved_value_can_be_deleted(as_researcher: TestClient, entry: str):
    value_id = saved_for(as_researcher, entry).json()["id"]
    assert as_researcher.delete(f"/api/v1/saved-values/{value_id}").status_code == 204
    assert as_researcher.get("/api/v1/saved-values").json()["total"] == 0


def test_somebody_elses_saved_value_does_not_exist(
    as_researcher: TestClient, entry: str, client_for, sessions
):
    from backend.tests.api.conftest import PASSWORD

    from app.application.auth import create_user

    value_id = saved_for(as_researcher, entry).json()["id"]
    email = f"other-{uuid.uuid4().hex[:8]}@example.org"
    with sessions() as session:
        create_user(
            session, email=email, display_name="Other", password=PASSWORD, role="researcher"
        )
        session.commit()
    stranger = client_for()
    stranger.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})

    # Personal, so another researcher's saved value is not merely unusable —
    # it is invisible.
    assert stranger.get("/api/v1/saved-values").json()["total"] == 0
    assert (
        stranger.patch(f"/api/v1/saved-values/{value_id}", json={"name": "mine"}).status_code == 404
    )
    assert stranger.delete(f"/api/v1/saved-values/{value_id}").status_code == 404


def test_an_untyped_field_cannot_be_saved_from(
    as_admin: TestClient, as_researcher: TestClient, revision: str
):
    """Saving a thread count under a name is not a feature, it is clutter."""
    slug = f"plain-{uuid.uuid4().hex[:8]}"
    created = as_admin.post(
        "/api/v1/publications/revisions",
        json={
            "slug": slug,
            "pipeline_revision_id": revision,
            "title": "Plain",
            "fields": [
                rules_field(),
                {
                    "key": "window",
                    "label": "Window",
                    "field_type": "integer",
                    "required": False,
                    "binding": {
                        "target": "step_parameter",
                        "stage": "fit",
                        "step": "a",
                        "binding_key": "n",
                    },
                },
            ],
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    as_admin.post(
        f"/api/v1/publications/{body['publication_id']}/publish",
        params={"revision_id": body["revision_id"]},
    )

    response = as_researcher.post(
        "/api/v1/saved-values",
        params={"entry": slug},
        json={"field_key": "window", "name": "five", "value": 5},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "saved_value.not_saveable"
