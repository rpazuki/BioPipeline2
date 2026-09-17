"""Task logs over HTTP.

What a task printed is the first thing anybody asks for when one fails, and
the run page had a sentence apologising for not having it.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

pytestmark = pytest.mark.db

DOC = """
pipeline: __NAME__
title: Log demo
defaults: {threads: 4}
stages:
  - name: only
    steps:
      - {name: a, package: labUtils.demo, method: run, parameters: {n: "{threads}"}}
    outputs:
      report: {path: "outputs/report.txt"}
"""


@pytest.fixture
def run_and_task(as_admin: TestClient, app) -> tuple[str, str]:
    source = DOC.replace("__NAME__", f"lg_{uuid.uuid4().hex[:8]}")
    revision = as_admin.post("/api/v1/pipelines/revisions", json={"source_text": source})
    assert revision.status_code == 201, revision.text
    submitted = as_admin.post(
        "/api/v1/runs",
        json={"pipeline_revision_id": revision.json()["revision_id"], "values": {}},
    )
    assert submitted.status_code == 201, submitted.text
    run_id = submitted.json()["run_id"]
    with Session(app.state.engine) as session:
        task_id = session.execute(
            text("SELECT id FROM run_tasks WHERE run_id = :r LIMIT 1"), {"r": run_id}
        ).scalar_one()
    return run_id, str(task_id)


def attempt(app, task_id: str, *, number: int = 1, finished: bool = False) -> str:
    with Session(app.state.engine) as session:
        attempt_id = session.execute(
            text(
                "INSERT INTO run_task_attempts "
                "(task_id, attempt_number, image_ref, status, exit_code, finished_at) "
                "VALUES (:t, :n, 'img:dev', :s, :c, "
                "        CASE WHEN :done THEN now() ELSE NULL END) RETURNING id"
            ),
            {
                "t": task_id,
                "n": number,
                "s": "failed" if finished else "running",
                "c": 1 if finished else None,
                "done": finished,
            },
        ).scalar_one()
        session.commit()
    return str(attempt_id)


def write_live_log(app, run_id: str, body: str, *, number: int = 1) -> None:
    logs = app.state.settings.workspace_root / run_id / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    (logs / f"attempt-{number}.log").write_text(body)


# --- reading -----------------------------------------------------------------


def test_a_running_task_s_log_can_be_watched(as_admin: TestClient, app, run_and_task):
    run_id, task_id = run_and_task
    attempt(app, task_id)
    write_live_log(app, run_id, "plate 1 of 12\n")

    response = as_admin.get(f"/api/v1/runs/{run_id}/tasks/{task_id}/log")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["text"] == "plate 1 of 12\n"
    # Which tells a client to keep asking.
    assert body["live"] is True
    assert body["artifact_id"] is None


def test_only_the_tail_comes_back_and_it_says_so(as_admin: TestClient, app, run_and_task):
    run_id, task_id = run_and_task
    attempt(app, task_id)
    write_live_log(app, run_id, "x" * 50_000 + "THE END")

    body = as_admin.get(
        f"/api/v1/runs/{run_id}/tasks/{task_id}/log", params={"tail_bytes": 2048}
    ).json()
    assert body["truncated"] is True
    assert body["bytes_read"] == 2048
    assert body["bytes_total"] == 50_007
    assert body["text"].endswith("THE END")


def test_an_absurd_tail_request_is_bounded(as_admin: TestClient, app, run_and_task):
    """This runs in the process that answers every other request."""
    run_id, task_id = run_and_task
    attempt(app, task_id)
    write_live_log(app, run_id, "hello\n")
    response = as_admin.get(
        f"/api/v1/runs/{run_id}/tasks/{task_id}/log", params={"tail_bytes": 10**12}
    )
    assert response.status_code == 200
    assert response.json()["text"] == "hello\n"


def test_an_earlier_attempt_can_be_asked_for(as_admin: TestClient, app, run_and_task):
    run_id, task_id = run_and_task
    attempt(app, task_id, number=1, finished=True)
    attempt(app, task_id, number=2)
    write_live_log(app, run_id, "first try\n", number=1)
    write_live_log(app, run_id, "second try\n", number=2)

    latest = as_admin.get(f"/api/v1/runs/{run_id}/tasks/{task_id}/log").json()
    first = as_admin.get(f"/api/v1/runs/{run_id}/tasks/{task_id}/log", params={"attempt": 1}).json()
    assert latest["text"] == "second try\n"
    assert first["text"] == "first try\n"


def test_a_task_never_attempted_is_a_404(as_admin: TestClient, run_and_task):
    run_id, task_id = run_and_task
    response = as_admin.get(f"/api/v1/runs/{run_id}/tasks/{task_id}/log")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "task.no_attempt"


def test_a_task_from_another_run_is_a_404(as_admin: TestClient, run_and_task):
    """The task id is real; it just is not in this run."""
    _, task_id = run_and_task
    response = as_admin.get(f"/api/v1/runs/{uuid.uuid4()}/tasks/{task_id}/log")
    assert response.status_code == 404


# --- attempts ----------------------------------------------------------------


def test_the_attempts_are_listed_newest_first(as_admin: TestClient, app, run_and_task):
    run_id, task_id = run_and_task
    attempt(app, task_id, number=1, finished=True)
    attempt(app, task_id, number=2)

    body = as_admin.get(f"/api/v1/runs/{run_id}/tasks/{task_id}/attempts").json()
    assert [item["attempt_number"] for item in body["items"]] == [2, 1]
    assert body["items"][1]["status"] == "failed"
    assert body["items"][1]["exit_code"] == 1


# --- who may see it ----------------------------------------------------------


def test_somebody_else_s_log_is_a_404(as_admin, as_researcher, app, run_and_task):
    run_id, task_id = run_and_task
    attempt(app, task_id)
    write_live_log(app, run_id, "secret\n")
    assert as_researcher.get(f"/api/v1/runs/{run_id}/tasks/{task_id}/log").status_code == 404


def test_reading_a_log_needs_a_signed_in_user(api: TestClient, run_and_task):
    run_id, task_id = run_and_task
    assert api.get(f"/api/v1/runs/{run_id}/tasks/{task_id}/log").status_code == 401
