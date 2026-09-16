"""What a task container is allowed to see.

Nothing populated `extra_mounts` until this existed, which meant a pipeline
whose input lived on shared storage was handed a path that did not exist
inside the container — the field was defined, documented and unit-tested on
the adapter, and never connected to anything.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.infrastructure.mounts import shared_root_mounts

pytestmark = pytest.mark.db


@pytest.fixture
def project(db: Session) -> uuid.UUID:
    return db.execute(text("SELECT id FROM projects WHERE is_default")).scalar_one()


@pytest.fixture
def admin(db: Session) -> uuid.UUID:
    return db.execute(
        text(
            "INSERT INTO users (email, display_name, role) VALUES (:e, 'A', 'admin') RETURNING id"
        ),
        {"e": f"m-{uuid.uuid4().hex[:10]}@example.org"},
    ).scalar_one()


def _add_root(db, project, tmp_path, **overrides) -> str:
    root_id = overrides.pop("id", f"root_{uuid.uuid4().hex[:8]}")
    values = {
        "id": root_id,
        "p": project,
        "label": "Lab results",
        "path": str(overrides.pop("root_path", tmp_path)),
        "readable": overrides.pop("readable", True),
        "writable": overrides.pop("writable", False),
        "mode": overrides.pop("identity_mode", "service_account"),
        "by": overrides.pop("attested_by", None),
        "at": overrides.pop("attested_at", "now()"),
    }
    db.execute(
        text(
            "INSERT INTO shared_storage_roots "
            "(id, project_id, label, root_path, readable, writable, identity_mode, "
            " attested_by, attested_at) "
            f"VALUES (:id, :p, :label, :path, :readable, :writable, :mode, :by, {values['at']})"
            if values["at"]
            else "INSERT INTO shared_storage_roots "
            "(id, project_id, label, root_path, readable, writable, identity_mode, "
            " attested_by, attested_at) "
            "VALUES (:id, :p, :label, :path, :readable, :writable, :mode, :by, NULL)"
        ),
        {k: v for k, v in values.items() if k != "at"},
    )
    return root_id


def test_a_readable_root_is_offered_at_its_own_path(db, project, admin, tmp_path):
    """The same path inside and outside.

    A pipeline's `{data_root}/plate.csv` is written by an author thinking about
    the lab's filesystem; mounting the root elsewhere would mean rewriting
    every path in every task spec, and any path missed would point at nothing.
    """
    _add_root(db, project, tmp_path, attested_by=admin)
    mounts = shared_root_mounts(db)
    assert mounts[str(tmp_path)] == str(tmp_path)


def test_a_root_that_does_not_exist_on_this_host_is_skipped(db, project, admin, tmp_path):
    """A worker on a host without the mount should run tasks that do not need
    it, rather than failing to start every container."""
    _add_root(db, project, tmp_path, root_path=tmp_path / "absent", attested_by=admin)
    assert str(tmp_path / "absent") not in shared_root_mounts(db)


def test_an_unreadable_root_is_not_offered(db, project, admin, tmp_path):
    _add_root(db, project, tmp_path, readable=False, writable=True, attested_by=admin)
    assert str(tmp_path) not in shared_root_mounts(db)


def test_a_requesting_user_root_may_be_unattested_and_is_still_skipped(db, project, tmp_path):
    """Attestation is the whole basis on which service-account access is safe
    (ADR 0013), so a root without one is not mounted."""
    _add_root(db, project, tmp_path, identity_mode="requesting_user", attested_at=None)
    assert str(tmp_path) not in shared_root_mounts(db)
