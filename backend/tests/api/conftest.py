"""API test fixtures.

The app is built against the test engine rather than a process-wide one, so
these run against the same database as everything else and roll back the same
way.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import CSRF_HEADER, CSRF_VALUE
from app.api.main import create_app
from app.application.auth import create_user
from app.settings import load_settings

PASSWORD = "correct-horse-battery"


@pytest.fixture
def app(engine: Engine, tmp_path):
    settings = load_settings(
        artifact_root=tmp_path / "artifacts",
        workspace_root=tmp_path / "workspaces",
        secure_cookies=False,
    )
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "workspaces").mkdir()
    return create_app(settings=settings, engine=engine)


@pytest.fixture
def client_for(app):
    """Build an independent client.

    A separate client per role, because a session lives in a cookie: two roles
    sharing one client means the second sign-in silently replaces the first,
    and a test asking for both gets whichever logged in last.
    """
    created: list[TestClient] = []

    def make() -> TestClient:
        client = TestClient(app)
        client.__enter__()
        # Every state-changing request carries the CSRF header, as the real
        # frontend does.
        client.headers.update({CSRF_HEADER: CSRF_VALUE})
        created.append(client)
        return client

    yield make
    for client in created:
        client.__exit__(None, None, None)


@pytest.fixture
def api(client_for) -> TestClient:
    return client_for()


@pytest.fixture
def sessions(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def _make_user(sessions, role: str) -> tuple[uuid.UUID, str]:
    email = f"{role}-{uuid.uuid4().hex[:10]}@example.org"
    with sessions() as session:
        user_id = create_user(
            session,
            email=email,
            display_name=role.title(),
            password=PASSWORD,
            role=role,
        )
        session.commit()
    return user_id, email


@pytest.fixture
def admin(sessions) -> tuple[uuid.UUID, str]:
    return _make_user(sessions, "admin")


@pytest.fixture
def researcher(sessions) -> tuple[uuid.UUID, str]:
    return _make_user(sessions, "researcher")


def _sign_in(client: TestClient, email: str) -> TestClient:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return client


@pytest.fixture
def as_admin(client_for, admin) -> TestClient:
    return _sign_in(client_for(), admin[1])


@pytest.fixture
def as_researcher(client_for, researcher) -> TestClient:
    return _sign_in(client_for(), researcher[1])


@pytest.fixture(autouse=True)
def cleanup(engine: Engine) -> Iterator[None]:
    """API tests commit, so they clean up after themselves.

    The transactional `db` fixture cannot be used here: the app opens its own
    sessions on its own connections, and a rolled-back transaction on one
    connection is invisible to another.
    """
    yield
    # Only what is deletable. Pipeline revisions are immutable by design, so
    # the pipelines and the users that own them stay; each test creates its
    # own with unique names, and leftovers are inert.
    with sessionmaker(bind=engine)() as session:
        session.execute(text("DELETE FROM run_deliveries"))
        session.execute(text("DELETE FROM artifacts"))
        session.execute(text("DELETE FROM run_task_attempts"))
        session.execute(text("DELETE FROM runs"))
        session.commit()
