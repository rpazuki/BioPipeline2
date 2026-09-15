"""Authentication over HTTP: sessions, CSRF, lockout, and authorization."""

from __future__ import annotations

import pytest
from backend.tests.api.conftest import PASSWORD
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.deps import CSRF_HEADER

pytestmark = pytest.mark.db


def test_signing_in_sets_an_http_only_cookie(api: TestClient, admin):
    _id, email = admin
    response = api.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    # A page script must not be able to read the token: an XSS bug could then
    # exfiltrate a session rather than merely act within one.
    assert "HttpOnly" in cookie


def test_the_session_endpoint_reports_the_signed_in_user(as_admin: TestClient, admin):
    _user_id, email = admin
    body = as_admin.get("/api/v1/auth/session").json()
    assert body["email"] == email
    assert body["role"] == "admin"


def test_wrong_credentials_are_refused(api: TestClient, admin):
    _id, email = admin
    response = api.post("/api/v1/auth/login", json={"email": email, "password": "wrong"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "auth.failed"


def test_an_unknown_address_fails_the_same_way(api: TestClient):
    """Distinguishing "no such user" from "wrong password" tells an attacker
    which addresses exist."""
    response = api.post("/api/v1/auth/login", json={"email": "ghost@example.org", "password": "x"})
    assert response.json()["error"]["code"] == "auth.failed"


def test_repeated_failures_lock_the_account(api: TestClient, admin, sessions):
    """Without a lockout a weak password is a matter of patience."""
    _id, email = admin
    for _ in range(10):
        api.post("/api/v1/auth/login", json={"email": email, "password": "wrong"})
    response = api.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "auth.locked"
    with sessions() as session:
        session.execute(text("UPDATE users SET locked_until = NULL WHERE email = :e"), {"e": email})
        session.commit()


def test_signing_out_ends_the_session(as_admin: TestClient):
    assert as_admin.post("/api/v1/auth/logout").status_code == 204
    assert as_admin.get("/api/v1/auth/session").status_code == 401


def test_changing_a_password_invalidates_the_session(as_admin: TestClient):
    """Every session the old password authorised dies immediately, including
    this one, rather than lingering until it happens to expire."""
    response = as_admin.post(
        "/api/v1/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "a-much-longer-secret"},
    )
    assert response.status_code == 204
    assert as_admin.get("/api/v1/auth/session").status_code == 401


def test_a_short_password_is_refused(as_admin: TestClient):
    response = as_admin.post(
        "/api/v1/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "short"},
    )
    assert response.status_code == 400


# --- CSRF -----------------------------------------------------------------


def test_a_state_changing_request_without_the_header_is_refused(api: TestClient, admin):
    """Cookie authentication means a browser attaches credentials to any
    request it is induced to make, so a mutation needs proof it came from our
    own code."""
    _id, email = admin
    # Removed from the client, not overridden per request: TestClient merges
    # client headers into every request, so a per-request omission is not one.
    del api.headers[CSRF_HEADER]
    response = api.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "auth.csrf_required"


def test_a_read_needs_no_csrf_header(as_admin: TestClient):
    del as_admin.headers[CSRF_HEADER]
    assert as_admin.get("/api/v1/auth/session").status_code == 200


# --- authorization --------------------------------------------------------


def test_an_admin_endpoint_refuses_a_researcher(as_researcher: TestClient):
    """Backend authorization is authoritative whatever the UI shows."""
    response = as_researcher.get("/api/v1/pipelines")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "auth.forbidden"


def test_an_admin_endpoint_accepts_an_admin(as_admin: TestClient):
    assert as_admin.get("/api/v1/pipelines").status_code == 200


def test_an_anonymous_caller_is_refused(api: TestClient):
    assert api.get("/api/v1/runs").status_code == 401
