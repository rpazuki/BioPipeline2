"""Environments over HTTP: what is installed, and installing it.

"What can I call?" is the authoring experience in a generic Python executor,
so reading an environment is open to anyone signed in and changing one is not.
"""

from __future__ import annotations

import uuid

import pytest
from backend.tests.api.conftest import COMPONENTS
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

from app.api.main import create_app
from app.settings import load_settings

pytestmark = pytest.mark.db

IMAGE = "biopipeline2/task-base:dev"


@pytest.fixture
def app(engine: Engine, tmp_path):
    settings = load_settings(
        artifact_root=tmp_path / "artifacts",
        workspace_root=tmp_path / "workspaces",
        environment_root=tmp_path / "environments",
        component_library_root=COMPONENTS,
        secure_cookies=False,
        task_default_image=IMAGE,
    )
    for name in ("artifacts", "workspaces", "environments"):
        (tmp_path / name).mkdir()
    return create_app(settings=settings, engine=engine)


def _clear(engine: Engine) -> None:
    with sessionmaker(bind=engine)() as session:
        session.execute(text("UPDATE runs SET environment_generation_id = NULL"))
        session.execute(text("UPDATE runtime_environments SET current_generation_id = NULL"))
        session.execute(text("DELETE FROM package_operations"))
        session.execute(text("DELETE FROM environment_generations"))
        session.execute(text("DELETE FROM runtime_environments"))
        session.commit()


@pytest.fixture(autouse=True)
def clean(engine: Engine):
    """Before as well as after.

    These run against the development database, where an environment created
    by hand is a perfectly ordinary thing to find — and "no environments" is
    one of the states worth asserting.
    """
    _clear(engine)
    yield
    with sessionmaker(bind=engine)() as session:
        session.execute(text("UPDATE runs SET environment_generation_id = NULL"))
        session.execute(text("UPDATE runtime_environments SET current_generation_id = NULL"))
        session.execute(text("DELETE FROM package_operations"))
        session.execute(text("DELETE FROM environment_generations"))
        session.execute(text("DELETE FROM runtime_environments"))
        session.commit()


def an_environment(db_session, *, name: str | None = None, generation: bool = True):
    """A ready environment placed directly, for the tests that are not about
    building one."""
    project = db_session.execute(text("SELECT id FROM projects WHERE is_default")).scalar_one()
    environment_id = db_session.execute(
        text(
            "INSERT INTO runtime_environments "
            "(project_id, name, venv_path, image_ref, status, is_default) "
            "VALUES (:p, :n, '/tmp/env', :i, 'available', true) RETURNING id"
        ),
        {"p": project, "n": name or f"lab-{uuid.uuid4().hex[:8]}", "i": IMAGE},
    ).scalar_one()
    if generation:
        generation_id = db_session.execute(
            text(
                "INSERT INTO environment_generations "
                "(environment_id, digest, generation_path, status, packages, python_version) "
                "VALUES (:e, :d, '/tmp/env', 'ready', :p, '3.12') RETURNING id"
            ),
            {
                "e": environment_id,
                "d": "sha256:" + uuid.uuid4().hex + uuid.uuid4().hex,
                "p": '{"items": [{"name": "pandas", "version": "2.2.1", "editable_path": null}]}',
            },
        ).scalar_one()
        db_session.execute(
            text("UPDATE runtime_environments SET current_generation_id = :g WHERE id = :i"),
            {"g": generation_id, "i": environment_id},
        )
    db_session.commit()
    return environment_id


def test_an_empty_deployment_has_no_environments(as_researcher: TestClient):
    """An ordinary state: tasks run against the image alone."""
    assert as_researcher.get("/api/v1/environments").json()["total"] == 0


def test_what_is_installed_is_readable_by_anyone_signed_in(as_researcher: TestClient, sessions):
    """Hiding the answer behind an admin role would make the authoring screen
    useless to the people using it."""
    with sessions() as session:
        environment_id = an_environment(session)

    body = as_researcher.get(f"/api/v1/environments/{environment_id}").json()

    assert body["package_count"] == 1
    assert body["packages"][0]["name"] == "pandas"
    assert body["reproducible"] is True
    assert body["reproducibility_note"] is None


def test_an_editable_install_says_the_run_cannot_be_reproduced(
    as_researcher: TestClient, sessions, engine: Engine
):
    with sessions() as session:
        environment_id = an_environment(session)
        session.execute(
            text(
                "UPDATE environment_generations SET editable = true, packages = :p "
                "WHERE environment_id = :e"
            ),
            {
                "e": environment_id,
                "p": '{"items": [{"name": "labUtils", "version": "0.4.0", '
                '"editable_path": "/srv/labUtils"}]}',
            },
        )
        session.commit()

    body = as_researcher.get(f"/api/v1/environments/{environment_id}").json()

    assert body["editable"] is True
    assert body["reproducible"] is False
    assert "labUtils (/srv/labUtils)" in body["reproducibility_note"]


def test_only_an_admin_may_install(as_researcher: TestClient, sessions):
    with sessions() as session:
        environment_id = an_environment(session)

    response = as_researcher.post(
        f"/api/v1/environments/{environment_id}/packages",
        json={"operation": "install", "specifier": "pandas"},
    )
    assert response.status_code == 403


def test_a_specifier_that_is_not_a_package_never_reaches_pip(as_admin: TestClient, sessions):
    """An install runs as an administrator on the machine that runs everybody's
    work, so a flag slipped into the box would be an install nobody reviewed."""
    with sessions() as session:
        environment_id = an_environment(session)

    response = as_admin.post(
        f"/api/v1/environments/{environment_id}/packages",
        json={"operation": "install", "specifier": "--index-url http://elsewhere pandas"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "package.specifier_invalid"


def test_a_busy_environment_says_what_it_is_doing(as_admin: TestClient, sessions):
    with sessions() as session:
        environment_id = an_environment(session)
        session.execute(
            text(
                "UPDATE runtime_environments SET locked_at = now(), "
                "locked_reason = 'install pandas' WHERE id = :i"
            ),
            {"i": environment_id},
        )
        session.commit()

    refused = as_admin.post(
        f"/api/v1/environments/{environment_id}/packages",
        json={"operation": "install", "specifier": "six"},
    )
    assert refused.status_code == 409
    assert "install pandas" in refused.json()["error"]["message"]

    # And a lock a crashed build left behind can be cleared.
    cleared = as_admin.post(f"/api/v1/environments/{environment_id}/unlock")
    assert cleared.status_code == 200
    assert cleared.json()["locked_reason"] is None


def test_an_environment_with_no_generation_cannot_be_inspected(as_researcher: TestClient, sessions):
    with sessions() as session:
        environment_id = an_environment(session, generation=False)

    response = as_researcher.get(f"/api/v1/environments/{environment_id}/callables")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "environment.not_ready"


def test_a_reclaimed_generation_is_still_on_the_list(as_admin: TestClient, sessions):
    """The janitor removes the directory, not the record.

    A run points at its generation for ever, so the row that says what that
    run imported has to outlive the bytes -- and an admin looking at the list
    has to be able to tell which builds still exist on disk.
    """
    with sessions() as session:
        environment_id = an_environment(session)
        session.execute(
            text(
                "INSERT INTO environment_generations "
                "(environment_id, digest, generation_path, status, packages, python_version, "
                " built_at, purged_at) VALUES (:e, :d, '/tmp/gone', 'ready', :p, '3.12', "
                " now() - interval '9 days', now() - interval '1 day')"
            ),
            {
                "e": environment_id,
                "d": "sha256:" + uuid.uuid4().hex + uuid.uuid4().hex,
                "p": '{"items": [{"name": "six", "version": "1.16.0", "editable_path": null}]}',
            },
        )
        session.commit()

    body = as_admin.get(f"/api/v1/environments/{environment_id}/generations").json()

    assert body["total"] == 2
    reclaimed = [item for item in body["items"] if item["reclaimed_at"]]
    assert len(reclaimed) == 1
    assert reclaimed[0]["current"] is False
    # Still says what it held, which is the point of keeping the row.
    assert reclaimed[0]["package_count"] == 1
    assert all(item["reclaimed_at"] is None for item in body["items"] if item["current"])


def test_an_environment_nobody_created_is_a_404(as_researcher: TestClient):
    assert as_researcher.get(f"/api/v1/environments/{uuid.uuid4()}").status_code == 404


@pytest.mark.slow
def test_an_install_goes_all_the_way_through_and_is_recorded(as_admin: TestClient):
    """The whole path, against a real container: create, install, history."""
    created = as_admin.post(
        "/api/v1/environments",
        json={"name": f"lab-{uuid.uuid4().hex[:8]}", "make_default": True},
    )
    if created.status_code == 503:
        pytest.skip("no container runtime")
    assert created.status_code == 201, created.text
    environment_id = created.json()["id"]

    installed = as_admin.post(
        f"/api/v1/environments/{environment_id}/packages",
        json={"operation": "install", "specifier": "six==1.16.0"},
    )
    assert installed.status_code == 200, installed.text
    assert installed.json()["status"] == "succeeded"

    detail = as_admin.get(f"/api/v1/environments/{environment_id}").json()
    assert "six" in {package["name"].lower() for package in detail["packages"]}

    # Provenance: what was asked for, by whom, and what it produced.
    operations = as_admin.get(f"/api/v1/environments/{environment_id}/operations").json()
    assert operations["items"][0]["specifier"] == "six==1.16.0"
    assert operations["items"][0]["resulting_digest"].startswith("sha256:")

    # And the generations are both there, because nothing is ever mutated.
    generations = as_admin.get(f"/api/v1/environments/{environment_id}/generations").json()
    assert generations["total"] == 2
    assert sum(1 for item in generations["items"] if item["current"]) == 1

    signatures = as_admin.get(
        f"/api/v1/environments/{environment_id}/callables", params={"module": "six"}
    ).json()
    assert any(item["name"] == "with_metaclass" for item in signatures["callables"])
