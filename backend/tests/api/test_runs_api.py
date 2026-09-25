"""Runs over HTTP: submit, inspect, cancel, and who may see what."""

from __future__ import annotations

import uuid

import pytest
from backend.tests.api.conftest import PASSWORD
from fastapi.testclient import TestClient
from sqlalchemy import text

pytestmark = pytest.mark.db

DOC_TEMPLATE = """
pipeline: __NAME__
title: API demo
defaults:
  data_root: $WILL_PROVIDE$
  threads: 4
inputs:
  data_root: {accept: directory, sources: [shared]}
stages:
  - name: only
    steps:
      - name: a
        package: labUtils.demo
        method: run
        parameters: {root: "{data_root}", n: "{threads}"}
    outputs:
      report: {path: "outputs/report.txt"}
"""


@pytest.fixture
def DOC() -> str:
    """A document whose pipeline name is unique to this test.

    Version numbers are per pipeline, and revisions are immutable, so a shared
    name would make assertions about versions depend on execution order.
    """
    import uuid

    return DOC_TEMPLATE.replace("__NAME__", f"api_demo_{uuid.uuid4().hex[:8]}")


@pytest.fixture
def revision(as_admin: TestClient, DOC: str) -> str:
    response = as_admin.post("/api/v1/pipelines/revisions", json={"source_text": DOC})
    assert response.status_code == 201, response.text
    return response.json()["revision_id"]


# --- authoring ------------------------------------------------------------


def test_a_document_becomes_a_revision(as_admin: TestClient, DOC: str):
    response = as_admin.post("/api/v1/pipelines/revisions", json={"source_text": DOC})
    assert response.status_code == 201
    body = response.json()
    assert body["version"] == 1
    assert body["graph_hash"].startswith("sha256:")


def test_a_broken_document_is_rejected_with_located_errors(as_admin: TestClient, DOC: str):
    response = as_admin.post(
        "/api/v1/pipelines/revisions",
        json={"source_text": DOC.replace('"{data_root}"', '"{nope}"')},
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "pipeline.compilation_failed"
    assert error["details"]["errors"][0]["location"]


def test_compile_preview_stores_nothing(as_admin: TestClient, DOC: str):
    """An author needs to see what a document will do before committing to a
    revision they cannot edit afterwards."""
    before = as_admin.get("/api/v1/pipelines").json()["items"]
    response = as_admin.post("/api/v1/pipelines/compile-preview", json={"source_text": DOC})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert [i["key"] for i in body["inputs"]] == ["data_root"]
    assert body["stages"][0]["steps"] == ["a"]
    after = as_admin.get("/api/v1/pipelines").json()["items"]
    assert len(after) == len(before)


def test_compile_preview_reports_errors_without_failing(as_admin: TestClient, DOC: str):
    response = as_admin.post(
        "/api/v1/pipelines/compile-preview",
        json={"source_text": DOC.replace('"{data_root}"', '"{nope}"')},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert any(d["severity"] == "error" for d in body["diagnostics"])


def test_a_misspelled_key_is_a_diagnostic_not_a_crash(as_admin: TestClient, DOC: str):
    """The commonest authoring mistake there is.

    Pydantic's own error used to escape the parser, which meant the endpoint
    whose entire purpose is to say what is wrong with a document answered 500
    for any document that was actually wrong.
    """
    response = as_admin.post(
        "/api/v1/pipelines/compile-preview",
        json={"source_text": DOC.replace("parameters:", "params:")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["diagnostics"], "a rejected document must say why"


def test_a_structural_problem_is_located_in_the_document(as_admin: TestClient, DOC: str):
    response = as_admin.post(
        "/api/v1/pipelines/compile-preview",
        json={"source_text": DOC.replace("parameters:", "params:")},
    )
    located = [d for d in response.json()["diagnostics"] if d["location"]]
    assert located, "a problem the author cannot find is a problem they cannot fix"
    assert located[0]["location"].startswith("stages.")


def test_yaml_that_does_not_parse_is_a_diagnostic_too(as_admin: TestClient):
    """Structural and semantic problems come back the same shape; which layer
    objected is not the author's business."""
    response = as_admin.post(
        "/api/v1/pipelines/compile-preview",
        json={"source_text": "pipeline: x\nstages: [\n"},
    )
    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert response.json()["diagnostics"]


def test_storing_a_structurally_broken_document_is_refused_not_a_crash(
    as_admin: TestClient, DOC: str
):
    response = as_admin.post(
        "/api/v1/pipelines/revisions",
        json={"source_text": DOC.replace("parameters:", "params:")},
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["details"]["errors"]


def test_a_revision_serves_the_contract_a_submission_must_satisfy(
    as_admin: TestClient, revision: str
):
    """Without this a client can only offer a free-text box, and the person
    filling it in has to already know the keys."""
    response = as_admin.get(f"/api/v1/pipelines/revisions/{revision}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert [i["key"] for i in body["inputs"]] == ["data_root"]
    declared = body["inputs"][0]
    assert declared["accept"] == "directory"
    assert declared["sources"] == ["shared"]
    assert declared["required"] is True


def test_a_revision_serves_what_it_will_produce(as_admin: TestClient, revision: str):
    body = as_admin.get(f"/api/v1/pipelines/revisions/{revision}").json()
    assert [o["key"] for o in body["outputs"]] == ["report"]
    assert body["outputs"][0]["stage"]
    assert body["outputs"][0]["delivery"] == ["download"]


def test_the_contract_is_the_one_compiled_for_that_revision(as_admin: TestClient, revision: str):
    """Read from the stored spec, not by recompiling the source.

    A revision is immutable, so what it declares today has to be what it
    declared when somebody published it -- recompiling would silently follow a
    compiler that has changed since.
    """
    body = as_admin.get(f"/api/v1/pipelines/revisions/{revision}").json()
    assert body["graph_hash"].startswith("sha256:")
    assert body["validation_status"] == "valid"


def test_an_unknown_revision_is_a_404(as_admin: TestClient):
    import uuid as _uuid

    response = as_admin.get(f"/api/v1/pipelines/revisions/{_uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "revision.not_found"


def test_reading_a_revision_is_admin_only(as_researcher: TestClient, revision: str):
    assert as_researcher.get(f"/api/v1/pipelines/revisions/{revision}").status_code == 403


def test_listing_a_pipelines_revisions_still_routes(as_admin: TestClient, DOC: str):
    """The two revision routes are the same length and must not shadow each
    other."""
    created = as_admin.post("/api/v1/pipelines/revisions", json={"source_text": DOC}).json()
    response = as_admin.get(f"/api/v1/pipelines/{created['pipeline_id']}/revisions")
    assert response.status_code == 200
    assert response.json()["items"][0]["revision_id"] == created["revision_id"]


# --- submitting -----------------------------------------------------------


def test_a_researcher_cannot_run_a_revision_directly(as_researcher: TestClient, revision):
    """The catalog is the researcher's route, and a route that bypasses it
    makes the publication a suggestion.

    A revision id is not a secret -- one appears in the metadata of every run
    -- so if this were open, anyone holding one could run an unpublished or
    withdrawn revision with values no publication would have allowed: no
    fixed values, no hidden fields, no type rules (ADR 0031).
    """
    response = as_researcher.post(
        "/api/v1/runs",
        json={"pipeline_revision_id": revision, "values": {"data_root": "/data/x"}},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "auth.forbidden"


def test_an_admin_runs_a_revision_they_just_wrote(as_admin: TestClient, revision):
    """The reason the endpoint exists: an author has to be able to run what
    they wrote before deciding to publish it."""
    response = as_admin.post(
        "/api/v1/runs",
        json={"pipeline_revision_id": revision, "values": {"data_root": "/data/x"}},
    )
    assert response.status_code == 201, response.text
    assert response.json()["task_count"] == 1


def test_a_direct_run_says_so_in_the_record(as_admin: TestClient, revision, sessions):
    """ "Which runs bypassed a publication" is a question somebody will ask,
    and the run row is the only place that can answer it."""
    run_id = as_admin.post(
        "/api/v1/runs",
        json={"pipeline_revision_id": revision, "values": {"data_root": "/data/x"}},
    ).json()["run_id"]

    with sessions() as session:
        row = session.execute(
            text("SELECT requested_from, publication_revision_id FROM runs WHERE id = :i"),
            {"i": run_id},
        ).one()

    assert row.requested_from == "admin"
    assert row.publication_revision_id is None


def test_a_missing_input_is_rejected(as_admin: TestClient, revision):
    response = as_admin.post("/api/v1/runs", json={"pipeline_revision_id": revision, "values": {}})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "run.submission_rejected"


def test_an_idempotency_key_makes_a_retry_safe(as_admin: TestClient, revision):
    """Without it a double-clicked submit starts a second run, which on shared
    compute can cost a day of alignment rather than nothing."""
    payload = {"pipeline_revision_id": revision, "values": {"data_root": "/data/x"}}
    headers = {"Idempotency-Key": "submit-once"}
    first = as_admin.post("/api/v1/runs", json=payload, headers=headers)
    second = as_admin.post("/api/v1/runs", json=payload, headers=headers)
    assert first.status_code == 201
    # Not a new resource: the caller is holding the one they already made.
    assert second.status_code == 200
    assert second.json()["reused"] is True
    assert second.json()["run_id"] == first.json()["run_id"]


def test_submissions_without_a_key_are_independent(as_admin: TestClient, revision):
    payload = {"pipeline_revision_id": revision, "values": {"data_root": "/data/x"}}
    first = as_admin.post("/api/v1/runs", json=payload)
    second = as_admin.post("/api/v1/runs", json=payload)
    assert first.json()["run_id"] != second.json()["run_id"]


# --- reading --------------------------------------------------------------


@pytest.fixture
def run_id(researcher, revision, sessions) -> str:
    """A run belonging to the researcher, placed directly.

    Not submitted over HTTP: the researcher's route is the catalog, which
    needs a publication, and everything below is about reading and cancelling
    a run rather than about how it was started.
    """
    from app.application.runs import submit_run

    with sessions() as session:
        submitted = submit_run(
            session,
            pipeline_revision_id=uuid.UUID(revision),
            requested_by=researcher[0],
            values={"data_root": "/data/x"},
        )
        session.commit()
    return str(submitted.run_id)


def test_a_run_reports_its_tasks(as_researcher: TestClient, run_id):
    body = as_researcher.get(f"/api/v1/runs/{run_id}").json()
    assert body["status"] == "queued"
    assert body["task_counts"] == {"queued": 1}
    assert body["input_values"]["data_root"] == "/data/x"


def test_the_task_list_is_available(as_researcher: TestClient, run_id):
    body = as_researcher.get(f"/api/v1/runs/{run_id}/tasks").json()
    assert body["total"] == 1
    assert body["items"][0]["status"] == "queued"


def test_artifacts_and_deliveries_are_listed(as_researcher: TestClient, run_id):
    assert as_researcher.get(f"/api/v1/runs/{run_id}/artifacts").json()["total"] == 0
    assert as_researcher.get(f"/api/v1/runs/{run_id}/deliveries").json()["total"] == 0


def test_a_failed_delivery_can_be_retried_from_the_run(as_researcher: TestClient, run_id, sessions):
    """The courier carries it; this only puts it back in the queue.

    An administrator mounts the share, and the researcher should not have to
    wait out a backoff they cannot see.
    """
    with sessions() as session:
        delivery_id = session.execute(
            text(
                "INSERT INTO run_deliveries "
                "(run_id, field_key, mode, status, target_root_id, message, attempts) "
                "VALUES (:r, 'results', 'shared', 'failed', 'lab-share', 'not mounted', 3) "
                "RETURNING id"
            ),
            {"r": run_id},
        ).scalar_one()
        session.commit()

    response = as_researcher.post(f"/api/v1/runs/{run_id}/deliveries/{delivery_id}/retry")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "pending"
    assert response.json()["attempts"] == 3


def test_retrying_a_delivery_that_is_not_there_is_a_404(as_researcher: TestClient, run_id):
    response = as_researcher.post(f"/api/v1/runs/{run_id}/deliveries/{uuid.uuid4()}/retry")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "delivery.not_found"


# --- visibility -----------------------------------------------------------


def test_a_researcher_sees_only_their_own_runs(
    api: TestClient, as_researcher: TestClient, run_id, sessions
):
    """And somebody else's run is a 404, not a 403: telling a caller that a
    resource exists but is not theirs leaks which runs exist."""
    from app.application.auth import create_user

    other = f"researcher-other-{run_id[:8]}@example.org"
    with sessions() as session:
        create_user(
            session,
            email=other,
            display_name="Other",
            password=PASSWORD,
            role="researcher",
        )
        session.commit()
    as_researcher.post("/api/v1/auth/logout")
    as_researcher.post("/api/v1/auth/login", json={"email": other, "password": PASSWORD})
    assert as_researcher.get("/api/v1/runs").json()["items"] == []
    assert as_researcher.get(f"/api/v1/runs/{run_id}").status_code == 404


def test_an_admin_sees_every_run(as_admin: TestClient, run_id):
    assert as_admin.get(f"/api/v1/runs/{run_id}").status_code == 200
    assert any(item["id"] == run_id for item in as_admin.get("/api/v1/runs").json()["items"])


# --- cancelling -----------------------------------------------------------


def test_cancelling_stops_queued_work(as_researcher: TestClient, run_id):
    response = as_researcher.post(f"/api/v1/runs/{run_id}/cancel")
    assert response.status_code == 200
    tasks = as_researcher.get(f"/api/v1/runs/{run_id}/tasks").json()["items"]
    assert all(task["status"] == "cancelled" for task in tasks)


def test_cancelling_is_idempotent(as_researcher: TestClient, run_id):
    as_researcher.post(f"/api/v1/runs/{run_id}/cancel")
    assert as_researcher.post(f"/api/v1/runs/{run_id}/cancel").status_code == 200


def test_an_unknown_run_is_a_404(as_researcher: TestClient):
    missing = "00000000-0000-0000-0000-000000000001"
    assert as_researcher.get(f"/api/v1/runs/{missing}").status_code == 404
