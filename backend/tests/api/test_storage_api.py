"""Registering a shared root over HTTP.

The endpoint that turns a fresh install into one somebody can use: until a
root exists, every submission that names a file the lab already has is refused.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.db


@pytest.fixture(autouse=True)
def only_our_roots(engine):
    """Clean up after ourselves.

    These tests commit, and the shared dev database also holds the roots the
    Phase 0b spike registered. Scoped by the identifier prefix so the spike's
    data survives.
    """
    yield
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    with Session(engine) as session:
        session.execute(text("DELETE FROM shared_storage_roots WHERE id LIKE 'lab-%'"))
        session.commit()


def payload(path, **overrides) -> dict:
    body = {
        "id": f"lab-{uuid.uuid4().hex[:8]}",
        "label": "Lab share",
        "root_path": str(path),
        "attestation_note": "Checked: every member of bio-lab already reads nas01:/lab.",
    }
    body.update(overrides)
    return body


def test_an_admin_registers_a_root(as_admin: TestClient, tmp_path):
    share = tmp_path / "lab"
    share.mkdir()
    response = as_admin.post("/api/v1/storage/roots", json=payload(share))
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["root_path"] == str(share)
    assert body["attested_at"] is not None
    # The two questions an operator actually has.
    assert body["visible"] is True
    assert body["in_use"] is True


def test_a_researcher_cannot(as_researcher: TestClient, tmp_path):
    """Registering a root is an attestation, not a preference."""
    share = tmp_path / "lab"
    share.mkdir()
    assert as_researcher.post("/api/v1/storage/roots", json=payload(share)).status_code == 403


def test_registering_needs_a_signed_in_user(api: TestClient, tmp_path):
    share = tmp_path / "lab"
    share.mkdir()
    assert api.post("/api/v1/storage/roots", json=payload(share)).status_code == 401


def test_a_refusal_says_which_rule_it_broke(as_admin: TestClient):
    response = as_admin.post("/api/v1/storage/roots", json=payload("/etc"))
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "storage_root.rejected"
    assert "system directory" in error["message"]


def test_the_artifact_store_is_refused_over_http_too(as_admin: TestClient, app):
    """The refusal that stops a shared-input feature becoming a way to read
    every other run's outputs."""
    response = as_admin.post(
        "/api/v1/storage/roots", json=payload(app.state.settings.artifact_root)
    )
    assert response.status_code == 422
    assert "artifact store" in response.json()["error"]["message"]


def test_a_root_with_no_attestation_note_is_refused(as_admin: TestClient, tmp_path):
    share = tmp_path / "lab"
    share.mkdir()
    response = as_admin.post("/api/v1/storage/roots", json=payload(share, attestation_note=""))
    # Refused by the request shape before it reaches the service: the note is
    # not an optional field with a validator, it is required.
    assert response.status_code in (400, 422)


def test_a_root_is_listed_and_can_be_withdrawn_and_put_back(as_admin: TestClient, tmp_path):
    share = tmp_path / "lab"
    share.mkdir()
    created = as_admin.post("/api/v1/storage/roots", json=payload(share)).json()
    root_id = created["id"]

    listed = as_admin.get("/api/v1/storage/roots").json()["items"]
    assert any(item["id"] == root_id and item["in_use"] for item in listed)

    withdrawn = as_admin.post(
        f"/api/v1/storage/roots/{root_id}/revoke", json={"reason": "Share decommissioned."}
    )
    assert withdrawn.status_code == 200, withdrawn.text
    assert withdrawn.json()["revoked_at"] is not None
    assert withdrawn.json()["in_use"] is False
    # Still listed, and still says who attested it.
    assert withdrawn.json()["attested_by"] is not None

    back = as_admin.post(
        f"/api/v1/storage/roots/{root_id}/reinstate",
        json={"attestation_note": "Re-checked after the group was restored."},
    )
    assert back.status_code == 200, back.text
    assert back.json()["in_use"] is True


def test_an_unknown_root_is_a_404(as_admin: TestClient):
    response = as_admin.post("/api/v1/storage/roots/nope/revoke", json={"reason": "whatever"})
    assert response.status_code == 404


def test_a_registered_root_is_what_a_submission_may_name(as_admin: TestClient, tmp_path, app):
    """The point of the whole endpoint.

    `readable_roots` is what a fan-out is confined to, and before a root
    exists it is empty — so nothing that names a real file can be submitted.
    """
    from sqlalchemy.orm import Session

    from app.infrastructure.mounts import readable_roots

    share = tmp_path / "lab"
    share.mkdir()
    with Session(app.state.engine) as session:
        assert share not in readable_roots(session)

    as_admin.post("/api/v1/storage/roots", json=payload(share))

    with Session(app.state.engine) as session:
        assert share in readable_roots(session)
