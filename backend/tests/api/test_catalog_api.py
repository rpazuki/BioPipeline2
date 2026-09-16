"""Publishing a catalog entry, and submitting against it.

The journey this feature exists for: an admin takes a compiled pipeline,
chooses which of its values a researcher may set, gives them names people use,
publishes it — and a researcher fills in a form without ever seeing a stage, a
step or a pipeline revision.
"""

from __future__ import annotations

import pathlib
import uuid

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.db

ROOT = pathlib.Path(__file__).resolve().parents[3]
EXAMPLE = ROOT / "examples/pipelines/od600_growth_rates.yaml"


@pytest.fixture
def pipeline_revision(as_admin: TestClient) -> str:
    source = EXAMPLE.read_text().replace(
        "pipeline: od600_growth_rates", f"pipeline: cat_{uuid.uuid4().hex[:8]}"
    )
    response = as_admin.post("/api/v1/pipelines/revisions", json={"source_text": source})
    assert response.status_code == 201, response.text
    return response.json()["revision_id"]


def field(**overrides) -> dict:
    base = {
        "key": "window",
        "label": "Smoothing window",
        "help_text": "How many points the fit averages over.",
        "field_type": "integer",
        "required": False,
        "default_value": 5,
        "binding": {
            "target": "step_parameter",
            "stage": "fit",
            "step": "df_fit_max_growth_rate",
            "binding_key": "moving_window_size",
        },
    }
    base.update(overrides)
    return base


def data_root_field(**overrides) -> dict:
    base = {
        "key": "experiment_folder",
        "label": "Experiment folder",
        "field_type": "directory",
        "required": True,
        "binding": {"target": "default_value", "binding_key": "data_root"},
    }
    base.update(overrides)
    return base


@pytest.fixture
def published(as_admin: TestClient, pipeline_revision: str) -> str:
    slug = f"od600-{uuid.uuid4().hex[:8]}"
    created = as_admin.post(
        "/api/v1/publications/revisions",
        json={
            "slug": slug,
            "pipeline_revision_id": pipeline_revision,
            "title": "OD600 growth rates",
            "description": "Fit growth curves from plate-reader exports.",
            "fields": [
                data_root_field(),
                {
                    "key": "mapping",
                    "label": "Mapping file",
                    "field_type": "file",
                    "required": True,
                    "binding": {"target": "default_value", "binding_key": "mapping_yaml"},
                },
                field(),
            ],
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


# --- publishing ------------------------------------------------------------


def test_a_publication_revision_is_created_and_versioned(as_admin, pipeline_revision):
    response = as_admin.post(
        "/api/v1/publications/revisions",
        json={
            "slug": f"p-{uuid.uuid4().hex[:8]}",
            "pipeline_revision_id": pipeline_revision,
            "title": "A title",
            "fields": [field()],
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["version"] == 1


def test_a_binding_to_a_step_that_does_not_exist_fails_the_publish(as_admin, pipeline_revision):
    """A form control wired to nothing must never reach the catalog."""
    broken = field(
        binding={
            "target": "step_parameter",
            "stage": "fit",
            "step": "df_does_not_exist",
            "binding_key": "moving_window_size",
        }
    )
    response = as_admin.post(
        "/api/v1/publications/revisions",
        json={
            "slug": f"p-{uuid.uuid4().hex[:8]}",
            "pipeline_revision_id": pipeline_revision,
            "title": "Broken",
            "fields": [broken],
        },
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "publication.invalid"
    assert error["details"]["errors"][0]["code"] == "binding.step_not_found"


def test_a_failed_publish_stores_nothing(as_admin, pipeline_revision):
    """A publication revision is immutable, so a broken one could only be
    superseded, never corrected."""
    slug = f"p-{uuid.uuid4().hex[:8]}"
    as_admin.post(
        "/api/v1/publications/revisions",
        json={
            "slug": slug,
            "pipeline_revision_id": pipeline_revision,
            "title": "Broken",
            "fields": [field(binding={"target": "default_value", "binding_key": "nope"})],
        },
    )
    listed = as_admin.get("/api/v1/publications").json()["items"]
    assert not any(item["slug"] == slug for item in listed)


def test_publishing_is_a_separate_step_from_creating(as_admin, pipeline_revision):
    """So an admin can look at the form a revision produces before researchers
    see it."""
    created = as_admin.post(
        "/api/v1/publications/revisions",
        json={
            "slug": f"p-{uuid.uuid4().hex[:8]}",
            "pipeline_revision_id": pipeline_revision,
            "title": "Draft",
            "fields": [field()],
        },
    ).json()
    listed = as_admin.get("/api/v1/publications").json()["items"]
    entry = next(item for item in listed if item["id"] == created["publication_id"])
    assert entry["status"] == "draft"
    assert entry["current_revision_id"] is None


# --- the catalog -----------------------------------------------------------


def test_a_researcher_sees_the_published_entry(as_researcher, published):
    entries = as_researcher.get("/api/v1/catalog").json()["items"]
    assert any(entry["slug"] == published for entry in entries)


def test_a_draft_is_not_in_the_catalog(as_researcher, as_admin, pipeline_revision):
    created = as_admin.post(
        "/api/v1/publications/revisions",
        json={
            "slug": f"draft-{uuid.uuid4().hex[:8]}",
            "pipeline_revision_id": pipeline_revision,
            "title": "Not yet",
            "fields": [field()],
        },
    ).json()
    slugs = {entry["slug"] for entry in as_researcher.get("/api/v1/catalog").json()["items"]}
    assert created["publication_id"] not in slugs


def test_the_form_is_described_in_the_admin_s_words(as_researcher, published):
    detail = as_researcher.get(f"/api/v1/catalog/{published}").json()
    keys = {item["key"]: item for item in detail["fields"]}
    assert keys["window"]["label"] == "Smoothing window"
    assert keys["window"]["help_text"].startswith("How many points")
    assert keys["experiment_folder"]["required"] is True


def test_the_catalog_does_not_publish_the_wiring(as_researcher, published):
    """Which parameter of which step a field feeds is the admin's business.

    Publishing it would tell every reader how the pipeline is put together and
    change nothing they could do about it.
    """
    body = as_researcher.get(f"/api/v1/catalog/{published}").text
    assert "binding" not in body
    assert "df_fit_max_growth_rate" not in body
    assert "moving_window_size" not in body


def test_an_archived_entry_leaves_the_catalog(as_admin, as_researcher, published):
    listed = as_admin.get("/api/v1/publications").json()["items"]
    publication_id = next(item["id"] for item in listed if item["current_revision_id"] is not None)
    as_admin.post(f"/api/v1/publications/{publication_id}/archive")
    assert as_researcher.get(f"/api/v1/catalog/{published}").status_code == 404


def test_an_unknown_entry_is_a_404(as_researcher):
    assert as_researcher.get("/api/v1/catalog/nope").status_code == 404


# --- submitting ------------------------------------------------------------


def test_a_missing_required_value_is_refused_by_label(as_researcher, published):
    """Named as the researcher sees it, not as the pipeline does."""
    response = as_researcher.post(f"/api/v1/catalog/{published}/runs", json={"values": {}})
    assert response.status_code == 422
    messages = [item["message"] for item in response.json()["error"]["details"]["errors"]]
    assert any("Experiment folder" in message for message in messages)


def test_a_field_the_entry_does_not_have_is_refused(as_researcher, published):
    response = as_researcher.post(
        f"/api/v1/catalog/{published}/runs",
        json={"values": {"experiment_folder": "/tmp", "mapping": "/tmp/m.yaml", "sneaky": 1}},
    )
    assert response.status_code == 422
    paths = [item["path"] for item in response.json()["error"]["details"]["errors"]]
    assert "values.sneaky" in paths


# --- a submission that actually runs ---------------------------------------


@pytest.fixture
def attested_root(sessions, tmp_path):
    """A shared root the fan-out may enumerate and a container could read."""
    import yaml
    from sqlalchemy import text as sql

    root = tmp_path / "lab"
    root.mkdir()
    for plate in ("plate_01", "plate_02"):
        (root / f"{plate}.csv").write_text("well,time_h,od600\nA1,0,0.1\n")
        (root / f"{plate}_meta.csv").write_text("well,group_id\nA1,g1\n")
    mapping = root / "mapping.yaml"
    mapping.write_text(
        yaml.safe_dump({f"{p}.csv": f"{p}_meta.csv" for p in ("plate_01", "plate_02")})
    )

    with sessions() as session:
        project_id = session.execute(sql("SELECT id FROM projects WHERE is_default")).scalar_one()
        admin_id = session.execute(
            sql(
                "INSERT INTO users (email, display_name, role) "
                "VALUES (:e, 'Root', 'admin') RETURNING id"
            ),
            {"e": f"root-{uuid.uuid4().hex[:8]}@example.org"},
        ).scalar_one()
        session.execute(
            sql(
                "INSERT INTO shared_storage_roots "
                "(id, project_id, label, root_path, readable, writable, identity_mode, "
                " attested_by, attested_at) "
                "VALUES (:i, :p, 'Lab', :path, true, false, 'service_account', :by, now())"
            ),
            {
                "i": f"lab_{uuid.uuid4().hex[:8]}",
                "p": project_id,
                "path": str(root),
                "by": admin_id,
            },
        )
        session.commit()
    return root, mapping


def test_a_catalog_submission_becomes_a_run(as_researcher, published, attested_root):
    root, mapping = attested_root
    response = as_researcher.post(
        f"/api/v1/catalog/{published}/runs",
        json={"values": {"experiment_folder": str(root), "mapping": str(mapping)}},
    )
    assert response.status_code == 201, response.text
    # Two plates, two matrix rows.
    assert response.json()["task_count"] == 4


def test_the_binding_reaches_every_task_plan(as_researcher, published, attested_root, sessions):
    """The point of the whole feature.

    A researcher sets "Smoothing window"; the value has to arrive as
    `moving_window_size` of `df_fit_max_growth_rate` — in *every* task, which
    means both matrix rows and both plates. A binding that reached three tasks
    out of four would produce a run whose halves disagree, and nothing on the
    run would say so.
    """
    from sqlalchemy import text as sql

    root, mapping = attested_root
    run_id = as_researcher.post(
        f"/api/v1/catalog/{published}/runs",
        json={
            "values": {
                "experiment_folder": str(root),
                "mapping": str(mapping),
                "window": 11,
            }
        },
    ).json()["run_id"]

    with sessions() as session:
        rows = list(
            session.execute(
                sql("SELECT task_key, task_spec FROM run_tasks WHERE run_id = :r"),
                {"r": run_id},
            )
        )
    assert len(rows) == 4
    for task_key, spec in rows:
        step = next(s for s in spec["steps"] if s["name"] == "df_fit_max_growth_rate")
        assert step["parameters"]["moving_window_size"] == 11, task_key


def test_an_unbound_parameter_keeps_the_pipeline_s_value(
    as_researcher, published, attested_root, sessions
):
    """Only what a field binds to may change. Everything else in the revision
    is what the author compiled."""
    from sqlalchemy import text as sql

    root, mapping = attested_root
    run_id = as_researcher.post(
        f"/api/v1/catalog/{published}/runs",
        json={
            "values": {
                "experiment_folder": str(root),
                "mapping": str(mapping),
                "window": 11,
            }
        },
    ).json()["run_id"]

    with sessions() as session:
        spec = session.execute(
            sql("SELECT task_spec FROM run_tasks WHERE run_id = :r LIMIT 1"), {"r": run_id}
        ).scalar_one()
    step = next(s for s in spec["steps"] if s["name"] == "df_fit_max_growth_rate")
    assert step["parameters"]["time_col"] == "time_h"


def test_the_run_records_what_the_researcher_filled_in(as_researcher, published, attested_root):
    """Not the translation. Six months later the run has to be readable by the
    person who submitted it, and `moving_window_size` is not what they typed
    into."""
    root, mapping = attested_root
    run_id = as_researcher.post(
        f"/api/v1/catalog/{published}/runs",
        json={
            "values": {
                "experiment_folder": str(root),
                "mapping": str(mapping),
                "window": 11,
            }
        },
    ).json()["run_id"]

    values = as_researcher.get(f"/api/v1/runs/{run_id}").json()["input_values"]
    assert values["window"] == 11
    assert "moving_window_size" not in values


def test_a_default_is_applied_when_a_field_is_left_blank(as_researcher, published, attested_root):
    root, mapping = attested_root
    run_id = as_researcher.post(
        f"/api/v1/catalog/{published}/runs",
        json={"values": {"experiment_folder": str(root), "mapping": str(mapping)}},
    ).json()["run_id"]
    values = as_researcher.get(f"/api/v1/runs/{run_id}").json()["input_values"]
    assert values["window"] == 5
