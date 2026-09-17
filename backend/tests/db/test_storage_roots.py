"""Which institutional paths may become a mount.

Registering a root is the first thing a deployment does and the only thing
that could previously be done only in SQL. Every test here is a path that must
be refused, or a refusal that must not happen — because the failures this
prevents are the invisible kind: a root that mounts nothing, a root whose
permissions are a fiction, and a root that hands every task container a
read-only view of every other run's outputs.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.application.storage_roots import (
    RootRejected,
    get_root,
    list_roots,
    register_root,
    reinstate,
    revoke,
)
from app.domain.errors import ValidationFailed
from app.infrastructure.mounts import readable_roots, shared_root_mounts
from app.settings import load_settings

pytestmark = pytest.mark.db


@pytest.fixture
def admin(db: Session) -> uuid.UUID:
    return db.execute(
        text(
            "INSERT INTO users (email, display_name, role) VALUES (:e, 'A', 'admin') RETURNING id"
        ),
        {"e": f"root-{uuid.uuid4().hex[:10]}@example.org"},
    ).scalar_one()


@pytest.fixture
def settings(tmp_path):
    """Settings whose platform paths are real, so overlap can be tested."""
    for name in ("artifacts", "workspaces", "components"):
        (tmp_path / name).mkdir()
    return load_settings(
        artifact_root=tmp_path / "artifacts",
        workspace_root=tmp_path / "workspaces",
        component_library_root=tmp_path / "components",
    )


def mine(db, tmp_path) -> set[str]:
    """Only the mounts this test made.

    The database is shared and the spike commits roots of its own, so an
    assertion about the whole table would pass or fail depending on what else
    has run.
    """
    return {path for path in shared_root_mounts(db) if path.startswith(str(tmp_path))}


def register(db, admin, settings, path, **overrides):
    defaults = {
        "root_id": f"root-{uuid.uuid4().hex[:8]}",
        "label": "Lab share",
        "root_path": str(path),
        "attested_by": admin,
        "attestation_note": "Every member of the lab already has read access to this share.",
        "settings": settings,
    }
    defaults.update(overrides)
    return register_root(db, **defaults)


# --- what a root may be ----------------------------------------------------


def test_a_real_directory_is_registered_and_mounted(db, admin, settings, tmp_path):
    share = tmp_path / "lab"
    share.mkdir()
    root = register(db, admin, settings, share)

    assert root.attested_at is not None
    assert str(share) in shared_root_mounts(db)
    # Mounted at its own path: a pipeline names `{data_root}/plate.csv` and
    # that has to mean the same thing inside the container.
    assert shared_root_mounts(db)[str(share)] == str(share)
    assert share in readable_roots(db)


def test_the_attestation_records_who_and_what(db, admin, settings, tmp_path):
    """The judgement the platform cannot make for itself."""
    share = tmp_path / "lab"
    share.mkdir()
    root = register(db, admin, settings, share, attestation_note="Checked group bio-lab on nas01.")
    assert root.attested_by == admin
    assert "nas01" in root.attestation_note


def test_an_attestation_with_nothing_written_in_it_is_refused(db, admin, settings, tmp_path):
    """A checkbox is not an attestation."""
    share = tmp_path / "lab"
    share.mkdir()
    with pytest.raises(RootRejected, match="what you are attesting"):
        register(db, admin, settings, share, attestation_note="   ")


def test_a_relative_path_is_refused(db, admin, settings):
    with pytest.raises(RootRejected, match="relative"):
        register(db, admin, settings, "data/lab")


def test_a_path_that_is_not_there_is_refused(db, admin, settings, tmp_path):
    """Rather than registered, listed, and mounted into nothing."""
    with pytest.raises(RootRejected, match="not a directory"):
        register(db, admin, settings, tmp_path / "missing")


def test_a_file_is_not_a_root(db, admin, settings, tmp_path):
    plate = tmp_path / "plate.csv"
    plate.write_text("od600\n")
    with pytest.raises(RootRejected, match="not a directory"):
        register(db, admin, settings, plate)


@pytest.mark.parametrize("path", ["/", "/etc", "/usr", "/proc"])
def test_a_system_directory_is_refused(db, admin, settings, path):
    with pytest.raises(RootRejected, match="system directory"):
        register(db, admin, settings, path)


def test_the_root_of_the_filesystem_is_refused_because_it_contains_everything(db, admin, settings):
    with pytest.raises(RootRejected, match="system directory"):
        register(db, admin, settings, "/")


# --- the platform's own storage --------------------------------------------


def test_the_artifact_store_cannot_be_registered(db, admin, settings):
    """The one that matters most.

    Mounted read-only into every task container, it would let any task read
    every other run's outputs — through the feature meant for reading inputs.
    """
    with pytest.raises(RootRejected, match="artifact store"):
        register(db, admin, settings, settings.artifact_root)


def test_a_parent_of_the_artifact_store_cannot_be_registered(db, admin, settings, tmp_path):
    with pytest.raises(RootRejected, match="artifact store"):
        register(db, admin, settings, tmp_path)


def test_a_directory_inside_the_artifact_store_cannot_be_registered(db, admin, settings):
    inside = settings.artifact_root / "runs"
    inside.mkdir(parents=True, exist_ok=True)
    with pytest.raises(RootRejected, match="artifact store"):
        register(db, admin, settings, inside)


def test_the_workspace_root_cannot_be_registered(db, admin, settings):
    with pytest.raises(RootRejected, match="workspace root"):
        register(db, admin, settings, settings.workspace_root)


# --- overlapping roots -----------------------------------------------------


def test_a_root_inside_an_existing_root_is_refused(db, admin, settings, tmp_path):
    """Their permissions could not both be true.

    Whichever is mounted exposes the other, so the narrower one's settings
    would be a fiction rather than a restriction.
    """
    outer = tmp_path / "share"
    inner = outer / "private"
    inner.mkdir(parents=True)
    register(db, admin, settings, outer)
    with pytest.raises(RootRejected, match="overlaps the registered root"):
        register(db, admin, settings, inner, readable=False, writable=True)


def test_a_root_containing_an_existing_root_is_refused(db, admin, settings, tmp_path):
    outer = tmp_path / "share"
    inner = outer / "plates"
    inner.mkdir(parents=True)
    register(db, admin, settings, inner)
    with pytest.raises(RootRejected, match="overlaps the registered root"):
        register(db, admin, settings, outer)


def test_two_siblings_are_fine(db, admin, settings, tmp_path):
    for name in ("plates", "sequencing"):
        (tmp_path / "share" / name).mkdir(parents=True)
    register(db, admin, settings, tmp_path / "share" / "plates")
    register(db, admin, settings, tmp_path / "share" / "sequencing")
    assert len(mine(db, tmp_path)) == 2


def test_a_duplicate_identifier_is_refused(db, admin, settings, tmp_path):
    for name in ("a", "b"):
        (tmp_path / name).mkdir()
    register(db, admin, settings, tmp_path / "a", root_id="lab")
    with pytest.raises(RootRejected, match="already exists"):
        register(db, admin, settings, tmp_path / "b", root_id="lab")


def test_an_identifier_that_is_not_one_is_refused(db, admin, settings, tmp_path):
    share = tmp_path / "lab"
    share.mkdir()
    with pytest.raises(RootRejected, match="usable identifier"):
        register(db, admin, settings, share, root_id="Lab Share!")


# --- withdrawing -----------------------------------------------------------


def test_a_withdrawn_root_stops_being_mounted(db, admin, settings, tmp_path):
    share = tmp_path / "lab"
    share.mkdir()
    root = register(db, admin, settings, share, root_id="lab")
    assert str(share) in shared_root_mounts(db)

    revoke(db, "lab", actor_id=admin, reason="The share was decommissioned.")
    assert mine(db, tmp_path) == set()
    assert root.revoked_at is not None


def test_withdrawing_keeps_the_record_of_who_attested_it(db, admin, settings, tmp_path):
    """Who signed for a root is history, not configuration."""
    share = tmp_path / "lab"
    share.mkdir()
    register(db, admin, settings, share, root_id="lab", attestation_note="Checked nas01.")
    revoke(db, "lab", actor_id=admin, reason="Decommissioned.")
    root = get_root(db, "lab").root
    assert root.attested_by == admin
    assert "nas01" in root.attestation_note
    assert root.metadata_["revoked_reason"] == "Decommissioned."


def test_withdrawing_twice_is_harmless(db, admin, settings, tmp_path):
    share = tmp_path / "lab"
    share.mkdir()
    register(db, admin, settings, share, root_id="lab")
    revoke(db, "lab", actor_id=admin, reason="one")
    first = get_root(db, "lab").root.revoked_at
    revoke(db, "lab", actor_id=admin, reason="two")
    assert get_root(db, "lab").root.revoked_at == first


def test_a_withdrawn_root_frees_its_path_for_another(db, admin, settings, tmp_path):
    share = tmp_path / "lab"
    share.mkdir()
    register(db, admin, settings, share, root_id="old")
    revoke(db, "old", actor_id=admin, reason="Re-registering with the right label.")
    register(db, admin, settings, share, root_id="new")
    assert str(share) in shared_root_mounts(db)


def test_reinstating_needs_a_fresh_attestation(db, admin, settings, tmp_path):
    """Not an undo: the reason for withdrawing may have been that the share's
    permissions changed, and re-signing the old statement would record a check
    nobody performed."""
    share = tmp_path / "lab"
    share.mkdir()
    register(db, admin, settings, share, root_id="lab", attestation_note="Original.")
    revoke(db, "lab", actor_id=admin, reason="Permissions under review.")

    with pytest.raises(RootRejected):
        reinstate(db, "lab", actor_id=admin, attestation_note="  ", settings=settings)

    reinstate(
        db,
        "lab",
        actor_id=admin,
        attestation_note="Re-checked, group restored.",
        settings=settings,
    )
    root = get_root(db, "lab").root
    assert root.revoked_at is None
    assert root.attestation_note == "Re-checked, group restored."
    assert str(share) in shared_root_mounts(db)


def test_reinstating_a_root_that_was_never_withdrawn_is_refused(db, admin, settings, tmp_path):
    share = tmp_path / "lab"
    share.mkdir()
    register(db, admin, settings, share, root_id="lab")
    with pytest.raises(ValidationFailed, match="not been withdrawn"):
        reinstate(db, "lab", actor_id=admin, attestation_note="again", settings=settings)


def test_a_root_whose_share_is_gone_says_so_rather_than_vanishing(db, admin, settings, tmp_path):
    """`shared_root_mounts` skips it silently, which is right there and
    invisible everywhere else. The list is where it has to be said."""
    share = tmp_path / "lab"
    share.mkdir()
    register(db, admin, settings, share, root_id="lab")
    share.rmdir()

    view = get_root(db, "lab")
    assert view.visible is False
    assert view.in_use is False
    assert view.root.readable is True  # still configured, just not there
    assert mine(db, tmp_path) == set()


def test_every_root_is_listed_working_or_not(db, admin, settings, tmp_path):
    for name in ("one", "two"):
        (tmp_path / name).mkdir()
    register(db, admin, settings, tmp_path / "one", root_id="one")
    register(db, admin, settings, tmp_path / "two", root_id="two")
    revoke(db, "two", actor_id=admin, reason="gone")
    listed = {view.root.id: view for view in list_roots(db)}
    assert {"one", "two"} <= set(listed)
    assert listed["one"].in_use is True
    # Withdrawn, and still listed: "the share is gone" and "nobody registered
    # it" are different problems.
    assert listed["two"].in_use is False
