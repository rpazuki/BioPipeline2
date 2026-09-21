"""The administrator's surface.

Three things a deployment could not do without shell access: add a person, see
whether the workers are alive, and find out who changed what. The third is the
one the schema has been ready for since the base migration with nothing
writing to it.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

pytestmark = pytest.mark.db


@pytest.fixture(autouse=True)
def clean_audit(engine: Engine):
    yield
    with sessionmaker(bind=engine)() as session:
        session.execute(text("DELETE FROM audit_events"))
        session.commit()


def new_account(client: TestClient, *, role: str = "researcher") -> dict:
    response = client.post(
        "/api/v1/admin/users",
        json={
            "email": f"new-{uuid.uuid4().hex[:8]}@example.org",
            "display_name": "A New Person",
            "role": role,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


# --- accounts --------------------------------------------------------------


def test_an_admin_can_add_a_person_without_shell_access(as_admin: TestClient, client_for):
    """The gap this closes: the only way to add a researcher was to run a
    script on the server."""
    created = new_account(as_admin)

    assert created["user"]["role"] == "researcher"
    assert created["user"]["must_change_password"] is True
    # Shown once, in this response, and nowhere else.
    assert len(created["one_time_password"]) >= 16

    signed_in = client_for()
    response = signed_in.post(
        "/api/v1/auth/login",
        json={"email": created["user"]["email"], "password": created["one_time_password"]},
    )
    assert response.status_code == 200
    assert response.json()["must_change_password"] is True


def test_a_generated_password_can_only_be_used_to_replace_itself(as_admin: TestClient, client_for):
    """An account an administrator created has a password they know. The only
    request that session may make is the one that ends that."""
    created = new_account(as_admin)
    person = client_for()
    person.post(
        "/api/v1/auth/login",
        json={"email": created["user"]["email"], "password": created["one_time_password"]},
    )

    refused = person.get("/api/v1/runs")
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "auth.password_change_required"
    # But they can see who they are, and change it.
    assert person.get("/api/v1/auth/session").status_code == 200

    changed = person.post(
        "/api/v1/auth/change-password",
        json={
            "current_password": created["one_time_password"],
            "new_password": "a-password-they-chose",
        },
    )
    assert changed.status_code == 204

    # Changing it ends every session it authorised, including this one.
    after = client_for()
    after.post(
        "/api/v1/auth/login",
        json={"email": created["user"]["email"], "password": "a-password-they-chose"},
    )
    assert after.get("/api/v1/runs").status_code == 200


def test_two_accounts_cannot_share_an_email(as_admin: TestClient):
    created = new_account(as_admin)
    clash = as_admin.post(
        "/api/v1/admin/users",
        json={
            "email": created["user"]["email"].upper(),
            "display_name": "Someone Else",
            "role": "researcher",
        },
    )
    # Upper case, because an email address is not case-sensitive and two
    # accounts that differ only in case are one account with two passwords.
    assert clash.status_code == 409
    assert clash.json()["error"]["code"] == "user.email_taken"


def test_a_role_change_ends_the_sessions_it_outranks(as_admin: TestClient, client_for):
    created = new_account(as_admin, role="admin")
    person = client_for()
    person.post(
        "/api/v1/auth/login",
        json={"email": created["user"]["email"], "password": created["one_time_password"]},
    )
    person.post(
        "/api/v1/auth/change-password",
        json={"current_password": created["one_time_password"], "new_password": "their-own-one"},
    )
    person = client_for()
    person.post(
        "/api/v1/auth/login",
        json={"email": created["user"]["email"], "password": "their-own-one"},
    )
    assert person.get("/api/v1/admin/users").status_code == 200

    demoted = as_admin.post(
        f"/api/v1/admin/users/{created['user']['id']}/role", json={"role": "researcher"}
    )
    assert demoted.status_code == 200

    # Not when their session happens to expire: now.
    assert person.get("/api/v1/admin/users").status_code == 401


def test_the_last_administrator_cannot_be_demoted_or_deactivated(
    as_admin: TestClient, sessions, admin
):
    """There is no recovery path that does not involve shell access to the
    database, which is what this screen exists to avoid needing."""
    with sessions() as session:
        session.execute(
            text("UPDATE users SET is_active = false WHERE role = 'admin' AND id <> :keep"),
            {"keep": admin[0]},
        )
        session.commit()

    demoted = as_admin.post(f"/api/v1/admin/users/{admin[0]}/role", json={"role": "researcher"})
    assert demoted.status_code == 409
    assert demoted.json()["error"]["code"] == "user.last_administrator"

    deactivated = as_admin.post(f"/api/v1/admin/users/{admin[0]}/deactivate")
    assert deactivated.status_code == 409

    with sessions() as session:
        session.execute(text("UPDATE users SET is_active = true WHERE role = 'admin'"))
        session.commit()


def test_a_deactivated_account_is_listed_rather_than_hidden(as_admin: TestClient):
    """ "They left" and "there was never an account" are different answers."""
    created = new_account(as_admin)
    as_admin.post(f"/api/v1/admin/users/{created['user']['id']}/deactivate")

    listed = as_admin.get("/api/v1/admin/users").json()["items"]
    theirs = next(item for item in listed if item["id"] == created["user"]["id"])
    assert theirs["is_active"] is False


def test_a_reset_issues_a_new_password_and_ends_every_session(as_admin: TestClient, client_for):
    created = new_account(as_admin)
    person = client_for()
    person.post(
        "/api/v1/auth/login",
        json={"email": created["user"]["email"], "password": created["one_time_password"]},
    )

    reset = as_admin.post(f"/api/v1/admin/users/{created['user']['id']}/reset-password")

    assert reset.status_code == 200
    assert reset.json()["one_time_password"] != created["one_time_password"]
    # An attacker holding a live session does not keep it because the
    # password changed.
    assert person.get("/api/v1/auth/session").status_code == 401


def test_only_an_admin_may_administer(as_researcher: TestClient):
    assert as_researcher.get("/api/v1/admin/users").status_code == 403
    assert as_researcher.get("/api/v1/admin/audit-events").status_code == 403
    assert as_researcher.get("/api/v1/admin/workers").status_code == 403
    assert as_researcher.get("/api/v1/admin/metrics").status_code == 403


# --- the fleet -------------------------------------------------------------


def test_the_fleet_says_when_each_worker_last_spoke(as_admin: TestClient, sessions):
    """A fleet quietly falling behind looks identical to a long queue."""
    worker_id = f"w-{uuid.uuid4().hex[:8]}"
    with sessions() as session:
        session.execute(
            text(
                "INSERT INTO workers (id, hostname, version, status, capacity, "
                " last_heartbeat_at) VALUES (:w, 'vm-1', '0.1.0', 'active', 4, "
                " now() - interval '90 seconds')"
            ),
            {"w": worker_id},
        )
        session.commit()

    listed = as_admin.get("/api/v1/admin/workers").json()["items"]
    mine = next(item for item in listed if item["id"] == worker_id)

    assert mine["hostname"] == "vm-1"
    assert mine["capacity"] == 4
    assert 80 < mine["heartbeat_age_seconds"] < 200

    with sessions() as session:
        session.execute(text("DELETE FROM workers WHERE id = :w"), {"w": worker_id})
        session.commit()


# --- what changed ----------------------------------------------------------


def test_every_administrative_change_is_recorded_with_who_and_what(as_admin: TestClient, admin):
    created = new_account(as_admin)
    as_admin.post(f"/api/v1/admin/users/{created['user']['id']}/role", json={"role": "admin"})

    events = as_admin.get("/api/v1/admin/audit-events").json()["items"]
    actions = [event["action"] for event in events]

    assert actions[:2] == ["user.role_changed", "user.created"]
    change = events[0]
    assert change["actor_email"] == admin[1]
    assert change["target_id"] == created["user"]["id"]
    # The detail that makes it answerable a year later.
    assert change["details"]["was"] == "researcher"
    assert change["details"]["now"] == "admin"
    # And the request id, so a line here joins a line in the server log.
    assert change["request_id"].startswith("req_")


def test_a_change_that_did_not_happen_is_not_recorded(as_admin: TestClient, sessions, admin):
    """The audit shares the transaction of the change it describes.

    A row saying a role changed when it did not is worse than silence,
    because it is the one people will believe.
    """
    with sessions() as session:
        session.execute(
            text("UPDATE users SET is_active = false WHERE role = 'admin' AND id <> :keep"),
            {"keep": admin[0]},
        )
        session.commit()

    refused = as_admin.post(f"/api/v1/admin/users/{admin[0]}/role", json={"role": "researcher"})
    assert refused.status_code == 409

    events = as_admin.get("/api/v1/admin/audit-events").json()["items"]
    assert [event for event in events if event["action"] == "user.role_changed"] == []

    with sessions() as session:
        session.execute(text("UPDATE users SET is_active = true WHERE role = 'admin'"))
        session.commit()


def test_the_log_can_be_narrowed_to_one_kind_of_thing(as_admin: TestClient):
    new_account(as_admin)

    filtered = as_admin.get(
        "/api/v1/admin/audit-events", params={"target_type": "storage_root"}
    ).json()
    assert filtered["total"] == 0

    users = as_admin.get("/api/v1/admin/audit-events", params={"target_type": "user"}).json()
    assert users["total"] >= 1


def test_attesting_a_storage_root_is_recorded_with_the_attestation(as_admin: TestClient, tmp_path):
    """The attestation is a human judgement the platform cannot verify, so who
    made it is the part worth keeping."""
    share = tmp_path / "pytest-of-share"
    share.mkdir()
    root_id = f"aud-{uuid.uuid4().hex[:6]}"
    registered = as_admin.post(
        "/api/v1/storage/roots",
        json={
            "id": root_id,
            "label": "Audited share",
            "root_path": str(share),
            "attestation_note": "Everyone reaching this platform is already in the lab group.",
            "readable": True,
            "writable": False,
        },
    )
    assert registered.status_code == 201, registered.text

    events = as_admin.get(
        "/api/v1/admin/audit-events", params={"target_type": "storage_root"}
    ).json()["items"]

    assert events[0]["action"] == "storage_root.registered"
    assert events[0]["details"]["root_id"] == root_id
    assert "lab group" in events[0]["details"]["attestation"]


# --- what an operator would be woken for ------------------------------------


def test_a_stale_worker_is_counted_separately_from_a_live_one(as_admin: TestClient, sessions):
    """The window the reaper has not reached yet: a worker has gone quiet and
    its tasks are still leased to it."""
    quiet = f"w-{uuid.uuid4().hex[:8]}"
    beating = f"w-{uuid.uuid4().hex[:8]}"
    with sessions() as session:
        session.execute(
            text(
                "INSERT INTO workers (id, hostname, version, status, capacity, "
                " last_heartbeat_at) VALUES (:q, 'vm-1', '0.1.0', 'active', 4, "
                " now() - interval '1 hour'), (:b, 'vm-2', '0.1.0', 'active', 4, now())"
            ),
            {"q": quiet, "b": beating},
        )
        session.commit()

    body = as_admin.get("/api/v1/admin/metrics").json()

    assert body["workers_stale"] >= 1
    assert body["workers_active"] >= 1
    # Free disk is read from the host this process runs on, so it is a number
    # rather than a guess -- and zero would mean the root is not mounted.
    assert body["artifact_root_free_bytes"] > 0

    with sessions() as session:
        session.execute(text("DELETE FROM workers WHERE id = ANY(:ids)"), {"ids": [quiet, beating]})
        session.commit()
