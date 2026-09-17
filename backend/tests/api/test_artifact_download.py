"""Getting results out.

The end of the journey the rest of the system exists for. Everything here is
either a byte that must arrive, a byte that must not, or a line in the read
audit that `audit_artifact_reads` has been promising since the settings were
written.
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
title: Download demo
defaults: {threads: 4}
stages:
  - name: only
    steps:
      - {name: a, package: labUtils.demo, method: run, parameters: {n: "{threads}"}}
    outputs:
      report: {path: "outputs/report.txt"}
"""


@pytest.fixture
def owned_run(as_admin: TestClient) -> str:
    source = DOC.replace("__NAME__", f"dl_{uuid.uuid4().hex[:8]}")
    revision = as_admin.post("/api/v1/pipelines/revisions", json={"source_text": source})
    assert revision.status_code == 201, revision.text
    submitted = as_admin.post(
        "/api/v1/runs",
        json={"pipeline_revision_id": revision.json()["revision_id"], "values": {}},
    )
    assert submitted.status_code == 201, submitted.text
    return submitted.json()["run_id"]


def store_artifact(
    app, run: str, *, filename: str, body: bytes | None = None, tree: dict[str, bytes] | None = None
) -> str:
    """Put real bytes in the store and a real row in the database.

    Promotion is exercised elsewhere; what is under test here is retrieval, so
    the artifact is placed rather than produced.
    """
    key = f"runs/{run}/only/attempt-1/{uuid.uuid4().hex[:8]}"
    target = app.state.settings.artifact_root / key
    size = 0
    if tree is not None:
        for name, content in tree.items():
            path = target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            size += len(content)
    else:
        assert body is not None
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        size = len(body)

    with Session(app.state.engine) as session:
        artifact_id = session.execute(
            text(
                "INSERT INTO artifacts "
                "(project_id, run_id, kind, storage_key, filename, size_bytes) "
                "VALUES ((SELECT project_id FROM runs WHERE id = :r), :r, 'task_output', "
                "        :k, :f, :s) RETURNING id"
            ),
            {"r": run, "k": key, "f": filename, "s": size},
        ).scalar_one()
        session.commit()
    return str(artifact_id)


def access_events(app, artifact_id: str) -> list[tuple[str, int | None]]:
    with Session(app.state.engine) as session:
        return [
            (row.access_type, row.bytes_served)
            for row in session.execute(
                text(
                    "SELECT access_type, bytes_served FROM artifact_access_events "
                    "WHERE artifact_id = :a ORDER BY created_at"
                ),
                {"a": artifact_id},
            ).all()
        ]


# --- a file ----------------------------------------------------------------


def test_the_bytes_come_back(as_admin: TestClient, app, owned_run):
    artifact = store_artifact(app, owned_run, filename="report.txt", body=b"mu_max,0.3466\n")
    response = as_admin.get(f"/api/v1/artifacts/{artifact}/download")
    assert response.status_code == 200, response.text
    assert response.content == b"mu_max,0.3466\n"


def test_a_download_is_always_an_attachment(as_admin: TestClient, app, owned_run):
    """An artifact's bytes were written by scientific code. Serving one inline
    under a type derived from its name would make the API a place to host
    whatever a task wrote."""
    artifact = store_artifact(
        app, owned_run, filename="evil.html", body=b"<script>alert(1)</script>"
    )
    response = as_admin.get(f"/api/v1/artifacts/{artifact}/download")
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "attachment" in response.headers["content-disposition"]


def test_the_filename_is_the_one_the_run_recorded(as_admin: TestClient, app, owned_run):
    artifact = store_artifact(app, owned_run, filename="report.txt", body=b"x")
    response = as_admin.get(f"/api/v1/artifacts/{artifact}/download")
    assert "report.txt" in response.headers["content-disposition"]


def test_a_range_can_be_asked_for(as_admin: TestClient, app, owned_run):
    """So a twenty-gigabyte alignment can be resumed rather than restarted."""
    artifact = store_artifact(app, owned_run, filename="big.bin", body=b"0123456789")
    response = as_admin.get(
        f"/api/v1/artifacts/{artifact}/download", headers={"Range": "bytes=2-5"}
    )
    assert response.status_code == 206
    assert response.content == b"2345"


# --- a directory of results ------------------------------------------------


def test_a_directory_lists_its_files_rather_than_packaging_them(
    as_admin: TestClient, app, owned_run
):
    """Building a multi-gigabyte archive inside the process that answers every
    other request is not a thing to do on a click."""
    artifact = store_artifact(
        app,
        owned_run,
        filename="plate_01",
        tree={"growth.csv": b"a,b\n", "fit/params.json": b"{}"},
    )
    detail = as_admin.get(f"/api/v1/artifacts/{artifact}").json()
    assert detail["is_directory"] is True
    assert {entry["path"] for entry in detail["files"]} == {"growth.csv", "fit/params.json"}
    assert all(entry["checksum_sha256"] for entry in detail["files"])


def test_one_file_inside_a_directory_comes_back(as_admin: TestClient, app, owned_run):
    artifact = store_artifact(
        app, owned_run, filename="plate_01", tree={"fit/params.json": b'{"mu":0.35}'}
    )
    response = as_admin.get(f"/api/v1/artifacts/{artifact}/files/fit/params.json")
    assert response.status_code == 200
    assert response.content == b'{"mu":0.35}'


def test_a_whole_directory_cannot_be_downloaded_as_one_file(as_admin: TestClient, app, owned_run):
    artifact = store_artifact(app, owned_run, filename="plate_01", tree={"a.csv": b"x"})
    response = as_admin.get(f"/api/v1/artifacts/{artifact}/download")
    assert response.status_code == 410
    assert "files it contains" in response.json()["error"]["message"]


@pytest.mark.parametrize("member", ["../../../etc/passwd", "fit/../../escape"])
def test_a_member_path_cannot_climb_out(as_admin: TestClient, app, owned_run, member):
    """`member` arrives from a URL. A path is not trusted for looking
    relative."""
    artifact = store_artifact(app, owned_run, filename="plate_01", tree={"a.csv": b"x"})
    response = as_admin.get(f"/api/v1/artifacts/{artifact}/files/{member}")
    assert response.status_code in (404, 410)


# --- who may have it -------------------------------------------------------


def test_somebody_else_s_artifact_is_a_404(as_admin: TestClient, as_researcher, app, owned_run):
    """404 rather than 403: telling a caller that something exists but is not
    theirs leaks which runs exist."""
    artifact = store_artifact(app, owned_run, filename="report.txt", body=b"secret")
    assert as_researcher.get(f"/api/v1/artifacts/{artifact}/download").status_code == 404
    assert as_researcher.get(f"/api/v1/artifacts/{artifact}").status_code == 404


def test_downloading_needs_a_signed_in_user(api: TestClient, app, owned_run):
    artifact = store_artifact(app, owned_run, filename="report.txt", body=b"x")
    assert api.get(f"/api/v1/artifacts/{artifact}/download").status_code == 401


def test_an_unknown_artifact_is_a_404(as_admin: TestClient):
    assert as_admin.get(f"/api/v1/artifacts/{uuid.uuid4()}/download").status_code == 404


# --- expiry ----------------------------------------------------------------


def test_an_expired_artifact_says_so_rather_than_denying_it_existed(
    as_admin: TestClient, app, owned_run
):
    """The run still succeeded, and the researcher is owed that distinction."""
    artifact = store_artifact(app, owned_run, filename="report.txt", body=b"x")
    with Session(app.state.engine) as session:
        session.execute(
            text("UPDATE artifacts SET deleted_at = now(), purged_at = now() WHERE id = :a"),
            {"a": artifact},
        )
        session.commit()

    detail = as_admin.get(f"/api/v1/artifacts/{artifact}").json()
    assert detail["available"] is False
    assert "retention" in detail["unavailable_reason"]

    download = as_admin.get(f"/api/v1/artifacts/{artifact}/download")
    assert download.status_code == 410
    assert download.json()["error"]["code"] == "artifact.unavailable"


def test_bytes_missing_from_the_store_are_reported_not_pretended(
    as_admin: TestClient, app, owned_run
):
    artifact = store_artifact(app, owned_run, filename="report.txt", body=b"x")
    with Session(app.state.engine) as session:
        key = session.execute(
            text("SELECT storage_key FROM artifacts WHERE id = :a"), {"a": artifact}
        ).scalar_one()
        session.commit()
    (app.state.settings.artifact_root / key).unlink()

    assert as_admin.get(f"/api/v1/artifacts/{artifact}").json()["available"] is False
    assert as_admin.get(f"/api/v1/artifacts/{artifact}/download").status_code == 410


# --- the read audit --------------------------------------------------------


def test_a_download_is_recorded(as_admin: TestClient, app, owned_run):
    """`audit_artifact_reads` has defaulted to true since the settings were
    written, and nothing wrote a row until there was a download path."""
    artifact = store_artifact(app, owned_run, filename="report.txt", body=b"0123456789")
    as_admin.get(f"/api/v1/artifacts/{artifact}/download")
    assert ("download", 10) in access_events(app, artifact)


def test_a_refusal_is_recorded_too(as_researcher: TestClient, app, owned_run):
    """Somebody walking artifact ids that are not theirs is exactly what a
    read audit is for."""
    artifact = store_artifact(app, owned_run, filename="report.txt", body=b"x")
    as_researcher.get(f"/api/v1/artifacts/{artifact}/download")
    assert [kind for kind, _ in access_events(app, artifact)] == ["denied"]


def test_nothing_is_recorded_when_auditing_is_off(client_for, engine, tmp_path, admin, owned_run):
    from app.api.main import create_app
    from app.settings import load_settings
    from tests.api.conftest import PASSWORD

    # Its own directories: the `app` fixture has already made the ones beside
    # them for the audited app.
    (tmp_path / "quiet-artifacts").mkdir()
    (tmp_path / "quiet-workspaces").mkdir()
    settings = load_settings(
        artifact_root=tmp_path / "quiet-artifacts",
        workspace_root=tmp_path / "quiet-workspaces",
        secure_cookies=False,
        audit_artifact_reads=False,
    )
    app = create_app(settings=settings, engine=engine)
    client = TestClient(app)
    client.__enter__()
    client.headers.update({"X-Requested-With": "BioPipeline2"})
    client.post("/api/v1/auth/login", json={"email": admin[1], "password": PASSWORD})
    try:
        artifact = store_artifact(app, owned_run, filename="report.txt", body=b"x")
        assert client.get(f"/api/v1/artifacts/{artifact}/download").status_code == 200
        assert access_events(app, artifact) == []
    finally:
        client.__exit__(None, None, None)
