"""Runs over HTTP: submit, inspect, cancel, and who may see what."""

from __future__ import annotations

import pytest
from backend.tests.api.conftest import PASSWORD
from fastapi.testclient import TestClient

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


# --- submitting -----------------------------------------------------------


def test_a_researcher_submits_a_run(as_researcher: TestClient, revision):
    response = as_researcher.post(
        "/api/v1/runs",
        json={"pipeline_revision_id": revision, "values": {"data_root": "/data/x"}},
    )
    assert response.status_code == 201, response.text
    assert response.json()["task_count"] == 1


def test_a_missing_input_is_rejected(as_researcher: TestClient, revision):
    response = as_researcher.post(
        "/api/v1/runs", json={"pipeline_revision_id": revision, "values": {}}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "run.submission_rejected"


def test_an_idempotency_key_makes_a_retry_safe(as_researcher: TestClient, revision):
    """Without it a double-clicked submit starts a second run, which on shared
    compute can cost a day of alignment rather than nothing."""
    payload = {"pipeline_revision_id": revision, "values": {"data_root": "/data/x"}}
    headers = {"Idempotency-Key": "submit-once"}
    first = as_researcher.post("/api/v1/runs", json=payload, headers=headers)
    second = as_researcher.post("/api/v1/runs", json=payload, headers=headers)
    assert first.status_code == 201
    # Not a new resource: the caller is holding the one they already made.
    assert second.status_code == 200
    assert second.json()["reused"] is True
    assert second.json()["run_id"] == first.json()["run_id"]


def test_submissions_without_a_key_are_independent(as_researcher: TestClient, revision):
    payload = {"pipeline_revision_id": revision, "values": {"data_root": "/data/x"}}
    first = as_researcher.post("/api/v1/runs", json=payload)
    second = as_researcher.post("/api/v1/runs", json=payload)
    assert first.json()["run_id"] != second.json()["run_id"]


# --- reading --------------------------------------------------------------


@pytest.fixture
def run_id(as_researcher: TestClient, revision) -> str:
    response = as_researcher.post(
        "/api/v1/runs",
        json={"pipeline_revision_id": revision, "values": {"data_root": "/data/x"}},
    )
    return response.json()["run_id"]


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
