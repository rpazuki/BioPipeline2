"""Health, readiness, and the configuration a browser boots from."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.deps import CSRF_HEADER, CSRF_VALUE
from app.api.errors import REQUEST_ID_HEADER
from app.api.main import create_app
from app.api.schemas import ClientConfigResponse
from app.settings import load_settings

pytestmark = pytest.mark.db


def test_health_needs_no_session(api: TestClient) -> None:
    response = api.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_every_response_carries_a_request_id(api: TestClient) -> None:
    assert api.get("/health").headers["X-Request-ID"].startswith("req_")


def test_a_supplied_request_id_survives(api: TestClient) -> None:
    """A trace has to survive the proxy hop, or the id is only useful to us."""
    response = api.get("/health", headers={"X-Request-ID": "req_from_the_proxy"})
    assert response.headers["X-Request-ID"] == "req_from_the_proxy"


def test_readiness_reports_each_dependency(api: TestClient) -> None:
    body = api.get("/ready").json()
    assert set(body["checks"]) == {"database", "artifact_root", "workspace_root"}


# --- client configuration -------------------------------------------------


def test_config_is_readable_without_a_session(api: TestClient) -> None:
    """The login page needs it before a session can exist."""
    assert api.get("/api/v1/config").status_code == 200


def test_config_publishes_the_csrf_header(api: TestClient) -> None:
    """Published rather than duplicated: a client that guesses it wrong fails
    every write, and it is not a secret."""
    body = api.get("/api/v1/config").json()
    assert body["csrf_header"] == CSRF_HEADER
    assert body["csrf_value"] == CSRF_VALUE


def test_config_exposes_exactly_the_allowlist() -> None:
    """The allowlist is the security boundary.

    A response model that drifts from ``Settings.public()`` either starves the
    frontend of a value it needs or publishes one nobody reviewed, and neither
    shows up as a failing test anywhere else.
    """
    published = set(load_settings().public())
    declared = set(ClientConfigResponse.model_fields)
    assert published <= declared, f"not served: {published - declared}"
    assert declared - published == {"csrf_header", "csrf_value"}


def test_config_carries_no_secret(api: TestClient) -> None:
    body = api.get("/api/v1/config").json()
    assert not any("secret" in key or "password" in key for key in body)
    assert "database_url" not in body


# --- failures ---------------------------------------------------------------
#
# These build their own app with a route that raises, because the thing under
# test is the middleware every route sits inside, not any particular route.


@pytest.fixture
def exploding(engine, tmp_path):
    settings = load_settings(
        artifact_root=tmp_path / "a",
        workspace_root=tmp_path / "w",
        secure_cookies=False,
        cors_origins=["http://localhost:3000"],
    )
    (tmp_path / "a").mkdir()
    (tmp_path / "w").mkdir()
    app = create_app(settings=settings, engine=engine)

    @app.get("/boom")
    def boom() -> None:  # pragma: no cover - raises by design
        raise RuntimeError("connection string: postgresql://user:hunter2@db/app")

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def test_an_unhandled_failure_still_carries_its_request_id(exploding: TestClient) -> None:
    """The one response where the reference matters most.

    Re-raising left the id on the floor: an internal error came back with no
    way to tie it to the log line holding the traceback, which is the only
    reason the id exists.
    """
    response = exploding.get("/boom", headers={"X-Request-ID": "req_traceable"})
    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "req_traceable"
    body = response.json()["error"]
    assert body["request_id"] == "req_traceable"
    assert body["code"] == "internal.error"


def test_an_unhandled_failure_says_nothing_about_the_exception(exploding: TestClient) -> None:
    assert "hunter2" not in exploding.get("/boom").text


def test_an_unhandled_failure_is_readable_cross_origin(exploding: TestClient) -> None:
    """Generated below the CORS layer, so a browser can actually read it.

    Left to the framework's own last-resort handler the response is built
    outside CORS, and the page sees an opaque network error with no status, no
    message and no request id -- at the exact moment somebody needs all three.
    """
    response = exploding.get("/boom", headers={"Origin": "http://localhost:3000"})
    assert response.status_code == 500
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_the_request_id_is_readable_cross_origin(exploding: TestClient) -> None:
    """A header a browser cannot read might as well not be sent."""
    response = exploding.get("/health", headers={"Origin": "http://localhost:3000"})
    assert REQUEST_ID_HEADER in response.headers["access-control-expose-headers"]
