"""Getting a file in.

The protocol is one number — where to continue — so most of what is worth
testing is what happens when that number is wrong: a chunk in the wrong place,
a client that gives up, a request that died between writing bytes and
recording them, bytes that are not the bytes the client said it was sending.

The limits here are tiny on purpose. A 64-byte chunk cap exercises exactly the
same code as a 64-megabyte one and leaves the suite fast.
"""

from __future__ import annotations

import hashlib
import uuid

import pytest
from backend.tests.api.conftest import COMPONENTS, PASSWORD
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

from app.api.main import create_app
from app.application.auth import create_user
from app.settings import load_settings

pytestmark = pytest.mark.db

CHUNK_MAX = 64
TOTAL_MAX = 4096


@pytest.fixture
def app(engine: Engine, tmp_path):
    settings = load_settings(
        artifact_root=tmp_path / "artifacts",
        workspace_root=tmp_path / "workspaces",
        component_library_root=COMPONENTS,
        secure_cookies=False,
        upload_chunk_max_bytes=CHUNK_MAX,
        upload_max_total_bytes=TOTAL_MAX,
    )
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "workspaces").mkdir()
    return create_app(settings=settings, engine=engine)


def start(client: TestClient, **body) -> dict:
    body.setdefault("filename", "plate_01.csv")
    response = client.post("/api/v1/uploads", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def append(client: TestClient, upload_id: str, offset: int, payload: bytes, *, total: str = "*"):
    end = offset + len(payload) - 1
    return client.patch(
        f"/api/v1/uploads/{upload_id}",
        content=payload,
        headers={"Content-Range": f"bytes {offset}-{end}/{total}"},
    )


def test_a_file_arrives_in_pieces_and_becomes_an_artifact(as_researcher: TestClient, app):
    body = b"plate,od\n" + b"a,0.5\n" * 20
    digest = hashlib.sha256(body).hexdigest()
    upload = start(as_researcher, declared_size_bytes=len(body), checksum_sha256=digest)

    offset = 0
    while offset < len(body):
        piece = body[offset : offset + CHUNK_MAX]
        response = append(as_researcher, upload["id"], offset, piece, total=str(len(body)))
        assert response.status_code == 200, response.text
        offset += len(piece)
        assert response.json()["received_bytes"] == offset

    finished = as_researcher.post(f"/api/v1/uploads/{upload['id']}/complete")
    assert finished.status_code == 200, finished.text
    assert finished.json()["status"] == "completed"
    assert finished.json()["reference"] == f"upload:{upload['id']}"

    artifact_id = finished.json()["artifact_id"]
    detail = as_researcher.get(f"/api/v1/artifacts/{artifact_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["checksum_sha256"] == digest
    assert detail.json()["size_bytes"] == len(body)

    # The whole point: the bytes come back out exactly as they went in.
    served = as_researcher.get(f"/api/v1/artifacts/{artifact_id}/download")
    assert served.status_code == 200
    assert served.content == body


def test_a_chunk_in_the_wrong_place_is_refused_with_the_right_place(as_researcher: TestClient):
    upload = start(as_researcher)
    assert append(as_researcher, upload["id"], 0, b"0123456789").status_code == 200

    late = append(as_researcher, upload["id"], 40, b"xxxx")
    assert late.status_code == 409
    error = late.json()["error"]
    assert error["code"] == "upload.offset_conflict"
    assert error["details"]["expected_offset"] == 10

    # And nothing was written: a refused chunk leaves the upload exactly where
    # it was, which is what makes the reported offset usable.
    current = as_researcher.get(f"/api/v1/uploads/{upload['id']}")
    assert current.json()["received_bytes"] == 10


def test_a_misplaced_chunk_on_a_finished_upload_still_says_where_to_go(
    as_researcher: TestClient,
):
    """Found by driving the real server, not by a test.

    An upload that has received every byte it declared has no allowance left,
    so a version of this that checked the size before the offset answered a
    stray chunk with 413. The client resumes on `upload.offset_conflict` and
    gives up on anything else, so the wrong status is the difference between
    recovering and losing the transfer.
    """
    body = b"complete"
    upload = start(as_researcher, declared_size_bytes=len(body))
    assert append(as_researcher, upload["id"], 0, body, total=str(len(body))).status_code == 200

    stray = append(as_researcher, upload["id"], 3, b"xxx", total=str(len(body)))
    assert stray.status_code == 409
    assert stray.json()["error"]["code"] == "upload.offset_conflict"
    assert stray.json()["error"]["details"]["expected_offset"] == len(body)

    # And the upload is still completable: the refusal changed nothing.
    assert as_researcher.post(f"/api/v1/uploads/{upload['id']}/complete").status_code == 200


def test_a_client_can_ask_where_it_got_to_and_carry_on(as_researcher: TestClient):
    upload = start(as_researcher)
    append(as_researcher, upload["id"], 0, b"first-half-")

    resumed = as_researcher.get(f"/api/v1/uploads/{upload['id']}")
    assert resumed.status_code == 200
    offset = resumed.json()["received_bytes"]
    assert offset == 11
    assert resumed.json()["chunk_max_bytes"] == CHUNK_MAX

    assert append(as_researcher, upload["id"], offset, b"second-half").status_code == 200
    finished = as_researcher.post(f"/api/v1/uploads/{upload['id']}/complete")
    assert finished.status_code == 200
    assert finished.json()["received_bytes"] == 22


def test_an_oversized_chunk_is_refused_and_appends_nothing(as_researcher: TestClient, app):
    upload = start(as_researcher)
    assert append(as_researcher, upload["id"], 0, b"a" * 10).status_code == 200

    too_big = append(as_researcher, upload["id"], 10, b"b" * (CHUNK_MAX + 1))
    assert too_big.status_code == 413
    assert too_big.json()["error"]["code"] == "upload.too_large"

    current = as_researcher.get(f"/api/v1/uploads/{upload['id']}")
    assert current.json()["received_bytes"] == 10
    staging = app.state.settings.artifact_root / f"uploads/staging/{upload['id']}"
    assert staging.stat().st_size == 10


def test_a_file_larger_than_the_deployment_takes_is_refused_before_it_is_sent(
    as_researcher: TestClient,
):
    response = as_researcher.post(
        "/api/v1/uploads",
        json={"filename": "genome.bam", "declared_size_bytes": TOTAL_MAX + 1},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "upload.too_large"
    # Told where the big files go, rather than just refused.
    assert "shared root" in response.json()["error"]["message"]


def test_the_wrong_bytes_are_not_certified(as_researcher: TestClient, app):
    upload = start(as_researcher, checksum_sha256=hashlib.sha256(b"what was sent").hexdigest())
    append(as_researcher, upload["id"], 0, b"what arrived!")

    failed = as_researcher.post(f"/api/v1/uploads/{upload['id']}/complete")
    assert failed.status_code == 422
    assert failed.json()["error"]["code"] == "upload.checksum_mismatch"

    # No artifact, no bytes, and no second chance at completing it: nobody
    # knows which chunk was wrong, so the upload ends here.
    state = as_researcher.get(f"/api/v1/uploads/{upload['id']}")
    assert state.json()["status"] == "aborted"
    assert state.json()["artifact_id"] is None
    assert not (app.state.settings.artifact_root / f"uploads/staging/{upload['id']}").exists()


def test_an_unfinished_upload_cannot_be_completed(as_researcher: TestClient):
    upload = start(as_researcher, declared_size_bytes=100)
    append(as_researcher, upload["id"], 0, b"only this much", total="100")

    response = as_researcher.post(f"/api/v1/uploads/{upload['id']}/complete")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "upload.incomplete"
    assert response.json()["error"]["details"]["received_bytes"] == 14


def test_completing_twice_gives_the_same_artifact(as_researcher: TestClient):
    upload = start(as_researcher)
    append(as_researcher, upload["id"], 0, b"content")
    first = as_researcher.post(f"/api/v1/uploads/{upload['id']}/complete")
    second = as_researcher.post(f"/api/v1/uploads/{upload['id']}/complete")

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["artifact_id"] == first.json()["artifact_id"]


def test_an_append_without_a_range_is_refused(as_researcher: TestClient):
    upload = start(as_researcher)
    response = as_researcher.patch(f"/api/v1/uploads/{upload['id']}", content=b"bytes")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "upload.range_required"


def test_an_abandoned_upload_releases_its_disk_and_takes_no_more(as_researcher: TestClient, app):
    upload = start(as_researcher)
    append(as_researcher, upload["id"], 0, b"half a file")
    staging = app.state.settings.artifact_root / f"uploads/staging/{upload['id']}"
    assert staging.exists()

    cancelled = as_researcher.delete(f"/api/v1/uploads/{upload['id']}")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "aborted"
    assert not staging.exists()

    assert append(as_researcher, upload["id"], 0, b"more").status_code == 409


def test_another_researchers_upload_does_not_exist(
    as_researcher: TestClient, client_for, sessions, admin
):
    upload = start(as_researcher)
    email = f"other-{uuid.uuid4().hex[:8]}@example.org"
    with sessions() as session:
        create_user(
            session, email=email, display_name="Other", password=PASSWORD, role="researcher"
        )
        session.commit()

    stranger = client_for()
    assert (
        stranger.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).status_code
        == 200
    )
    # Not 403: "it exists but is not yours" tells a stranger what other people
    # are working on, which is the same reason another researcher's run is a
    # 404.
    assert stranger.get(f"/api/v1/uploads/{upload['id']}").status_code == 404
    assert append(stranger, upload["id"], 0, b"theirs").status_code == 404
    assert stranger.delete(f"/api/v1/uploads/{upload['id']}").status_code == 404

    # An admin is the exception, and deliberately: they can already see every
    # run and every artifact in the deployment.
    supervisor = client_for()
    supervisor.post("/api/v1/auth/login", json={"email": admin[1], "password": PASSWORD})
    assert supervisor.get(f"/api/v1/uploads/{upload['id']}").status_code == 200


def test_an_upload_nobody_owns_is_a_404(as_researcher: TestClient):
    assert as_researcher.get(f"/api/v1/uploads/{uuid.uuid4()}").status_code == 404


def test_bytes_written_but_never_recorded_are_discarded(as_researcher: TestClient, app):
    """The crash case: a request wrote to the file and died before committing.

    The row is what the client was told, so the file is cut back to it. The
    alternative is a file that is longer than anyone knows, and a checksum
    over bytes nobody acknowledged.
    """
    upload = start(as_researcher)
    append(as_researcher, upload["id"], 0, b"recorded")
    staging = app.state.settings.artifact_root / f"uploads/staging/{upload['id']}"
    with staging.open("ab") as handle:
        handle.write(b"-orphaned-")

    assert append(as_researcher, upload["id"], 8, b"-real").status_code == 200
    finished = as_researcher.post(f"/api/v1/uploads/{upload['id']}/complete")
    assert finished.status_code == 200
    served = as_researcher.get(f"/api/v1/artifacts/{finished.json()['artifact_id']}/download")
    assert served.content == b"recorded-real"


def test_an_upload_is_cleaned_up_with_its_row(as_researcher: TestClient, app, engine: Engine):
    """Expiry releases the disk, not just the status column."""
    from app.infrastructure.artifacts import PosixArtifactStore
    from app.workers.reaper import expire_uploads

    upload = start(as_researcher)
    append(as_researcher, upload["id"], 0, b"abandoned")
    staging = app.state.settings.artifact_root / f"uploads/staging/{upload['id']}"
    assert staging.exists()

    with sessionmaker(bind=engine)() as session:
        session.execute(
            text("UPDATE uploads SET expires_at = now() - interval '1 hour' WHERE id = :i"),
            {"i": upload["id"]},
        )
        session.commit()
        store = PosixArtifactStore(app.state.settings.artifact_root)
        assert expire_uploads(session, store) == 1
        session.commit()

    assert not staging.exists()
    assert as_researcher.get(f"/api/v1/uploads/{upload['id']}").json()["status"] == "expired"


# --- an upload is only worth having if a run can read it --------------------

DOC = """
pipeline: __NAME__
title: Upload demo
defaults:
  sample_file: $WILL_PROVIDE$
inputs:
  sample_file: {accept: file, sources: [upload]}
stages:
  - name: only
    inputs:
      sample: "{sample_file}"
    steps:
      - {name: a, package: labUtils.demo, method: run, parameters: {n: 1}}
    outputs:
      report: {path: "outputs/report.txt"}
"""


@pytest.fixture
def revision(as_admin: TestClient) -> str:
    """Authoring is admin-only; submitting against it is not."""
    source = DOC.replace("__NAME__", f"up_{uuid.uuid4().hex[:8]}")
    created = as_admin.post("/api/v1/pipelines/revisions", json={"source_text": source})
    assert created.status_code == 201, created.text
    return created.json()["revision_id"]


def uploaded(client: TestClient, body: bytes = b"od600\n0.4\n") -> dict:
    upload = start(client, filename="plate_01.csv", declared_size_bytes=len(body))
    assert append(client, upload["id"], 0, body, total=str(len(body))).status_code == 200
    finished = client.post(f"/api/v1/uploads/{upload['id']}/complete")
    assert finished.status_code == 200, finished.text
    return finished.json()


def submit_as(sessions, revision: str, user_id, values: dict):
    """Submit as a given person, through the application rather than HTTP.

    `POST /runs` is admin-only (evaluation 1, E1-02): a researcher's route is
    the catalog, where a publication decides what the form contains. These
    tests are about what an *upload reference* does at submission, which is
    the same code either way, so the run is placed directly rather than
    dragging a publication into every one of them.
    """
    from app.application.runs import submit_run

    with sessions() as session:
        submitted = submit_run(
            session,
            pipeline_revision_id=uuid.UUID(revision),
            requested_by=user_id,
            values=values,
        )
        session.commit()
        return submitted


def test_an_uploaded_file_becomes_the_input_a_container_reads(
    as_researcher: TestClient, researcher, revision: str, engine: Engine, sessions
):
    upload = uploaded(as_researcher)
    run_id = str(
        submit_as(sessions, revision, researcher[0], {"sample_file": upload["reference"]}).run_id
    )

    with sessionmaker(bind=engine)() as session:
        spec, staged, recorded = session.execute(
            text(
                "SELECT t.task_spec, r.compiled_run_spec, "
                "  (SELECT value FROM run_field_values WHERE run_id = r.id LIMIT 1) "
                "FROM runs r JOIN run_tasks t ON t.run_id = r.id WHERE r.id = :i"
            ),
            {"i": run_id},
        ).one()

    # Workspace-relative, because the container has no idea where the host
    # keeps its artifacts and the runner resolves this against /work.
    assert spec["inputs"]["sample"] == f"inputs/{upload['id']}/plate_01.csv"
    assert staged["staged_inputs"] == [
        {"artifact_id": upload["artifact_id"], "path": f"inputs/{upload['id']}/plate_01.csv"}
    ]
    # The reference is what was recorded, not the resolved path: submitting
    # this run again has to mean the same file, not a workspace that is gone.
    assert recorded == upload["reference"]


def test_an_unfinished_upload_cannot_be_submitted(
    as_researcher: TestClient, researcher, revision: str, sessions
):
    from app.application.runs import SubmissionRejected

    upload = start(as_researcher)
    append(as_researcher, upload["id"], 0, b"half")

    with pytest.raises(SubmissionRejected) as refused:
        submit_as(sessions, revision, researcher[0], {"sample_file": f"upload:{upload['id']}"})

    errors = refused.value.details["errors"]
    # Located on the field, so the form can put it next to the control the
    # researcher used rather than at the top as a mystery.
    assert errors[0]["location"] == "inputs.sample_file"
    assert errors[0]["code"] == "input.upload_unavailable"


def test_another_researchers_upload_cannot_be_submitted(
    as_researcher: TestClient, sessions, revision: str
):
    from app.application.runs import SubmissionRejected

    upload = uploaded(as_researcher)
    email = f"other-{uuid.uuid4().hex[:8]}@example.org"
    with sessions() as session:
        stranger = create_user(
            session, email=email, display_name="Other", password=PASSWORD, role="researcher"
        )
        session.commit()

    with pytest.raises(SubmissionRejected) as refused:
        submit_as(sessions, revision, stranger, {"sample_file": upload["reference"]})

    assert "does not belong to you" in refused.value.details["errors"][0]["message"]
