"""Carrying a run's outputs to the lab's own storage.

`_plan_deliveries` has been writing `pending` rows since promotion existed and
nothing acted on one. What is under test here is the acting: that the bytes
arrive, that a delivery which cannot happen says why, and — more than
anything — that nothing on somebody else's filesystem is ever overwritten.
"""

from __future__ import annotations

import pathlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.application.deliveries import (
    DeliveryRefused,
    deliver_one,
    destination_for,
    due_delivery_ids,
    retry_delivery,
)
from app.application.pipelines import create_revision
from app.application.runs import submit_run
from app.application.storage_roots import register_root
from app.domain.enums import DeliveryMode, DeliveryStatus
from app.infrastructure.artifacts import PosixArtifactStore
from app.infrastructure.db.models import Artifact, RunDelivery, SharedStorageRoot
from app.settings import load_settings
from app.workers.courier import Courier

pytestmark = pytest.mark.db

DOC = """
pipeline: __NAME__
defaults: {root: /d}
stages:
  - name: fit
    steps:
      - {name: a, package: labUtils.x, method: run}
    outputs:
      results:
        path: "outputs/results"
        delivery: [shared]
        shared_root: lab-share
"""


@pytest.fixture
def settings(tmp_path):
    return load_settings(
        artifact_root=tmp_path / "artifacts", workspace_root=tmp_path / "workspaces"
    )


@pytest.fixture
def store(settings) -> PosixArtifactStore:
    return PosixArtifactStore(settings.artifact_root)


@pytest.fixture
def user(db: Session) -> uuid.UUID:
    return db.execute(
        text(
            "INSERT INTO users (email, display_name, role) VALUES (:e, 'D', 'admin') RETURNING id"
        ),
        {"e": f"del-{uuid.uuid4().hex[:10]}@example.org"},
    ).scalar_one()


@pytest.fixture
def share(db: Session, user, settings, tmp_path) -> SharedStorageRoot:
    """A writable, attested root, registered the way an admin registers one."""
    path = tmp_path / "lab-share"
    path.mkdir()
    return register_root(
        db,
        root_id="lab-share",
        label="Lab share",
        root_path=str(path),
        readable=True,
        writable=True,
        attested_by=user,
        attestation_note="Everyone who can reach this platform is already in the lab group.",
        settings=settings,
    )


def a_delivery(
    db: Session,
    user,
    store: PosixArtifactStore,
    *,
    root_id: str | None = "lab-share",
    body: bytes = b"od600,rate\nA1,0.42\n",
    tree: dict[str, bytes] | None = None,
) -> RunDelivery:
    """A run, an artifact with real bytes, and a pending delivery for it."""
    revision = create_revision(
        db, source_text=DOC.replace("__NAME__", f"dl_{uuid.uuid4().hex[:8]}"), owner_id=user
    )
    submitted = submit_run(
        db, pipeline_revision_id=revision.revision_id, requested_by=user, values={}
    )
    task_id = db.execute(
        text("SELECT id FROM run_tasks WHERE run_id = :r LIMIT 1"), {"r": submitted.run_id}
    ).scalar_one()
    project = db.execute(text("SELECT id FROM projects WHERE is_default")).scalar_one()

    key = f"runs/{submitted.run_id}/fit/attempt-1/results"
    path = store.path_for(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    if tree is not None:
        path.mkdir()
        for name, content in tree.items():
            (path / name).write_bytes(content)
    else:
        path.write_bytes(body)

    artifact = Artifact(
        project_id=project,
        run_id=submitted.run_id,
        task_id=task_id,
        owner_id=user,
        kind="task_output",
        storage_backend="posix",
        storage_key=key,
        filename="results" if tree is not None else "results.csv",
        size_bytes=0 if tree is not None else len(body),
    )
    db.add(artifact)
    db.flush()

    delivery = RunDelivery(
        run_id=submitted.run_id,
        task_id=task_id,
        field_key="results",
        mode=DeliveryMode.SHARED,
        artifact_id=artifact.id,
        target_root_id=root_id,
        status=DeliveryStatus.PENDING,
        message="awaiting delivery to the shared root",
    )
    db.add(delivery)
    db.flush()
    return delivery


def test_the_bytes_reach_the_share(db: Session, user, store, share):
    delivery = a_delivery(db, user, store)

    report = deliver_one(db, delivery.id, store=store)

    assert report.delivered
    landed = pathlib.Path(report.target_path or "")
    assert landed.read_bytes() == b"od600,rate\nA1,0.42\n"
    assert landed.is_relative_to(share.root_path)
    # Under a directory the platform made, never at the root of the share:
    # a lab's own files are not something to land on top of.
    assert landed.parent != pathlib.Path(share.root_path)

    db.refresh(delivery)
    assert delivery.status == DeliveryStatus.DELIVERED.value
    assert delivery.target_path == str(landed)
    assert delivery.delivered_at is not None
    assert delivery.message is None


def test_the_path_says_which_run_and_which_task(db: Session, user, store, share):
    delivery = a_delivery(db, user, store)
    artifact = db.get(Artifact, delivery.artifact_id)

    target = destination_for(db, delivery, share, artifact)

    # A researcher has to be able to find this without being told the layout.
    assert str(delivery.run_id)[:8] in str(target)
    assert "/fit/" in str(target) or target.parent.name == "fit"
    assert target.name == "results.csv"


def test_a_directory_output_arrives_as_a_directory(db: Session, user, store, share):
    delivery = a_delivery(db, user, store, tree={"a.csv": b"one", "b.csv": b"two"})

    report = deliver_one(db, delivery.id, store=store)

    assert report.delivered
    landed = pathlib.Path(report.target_path or "")
    assert sorted(p.name for p in landed.iterdir()) == ["a.csv", "b.csv"]


def test_nothing_on_the_share_is_ever_overwritten(db: Session, user, store, share):
    """The rule worth more than any amount of retrying."""
    delivery = a_delivery(db, user, store)
    artifact = db.get(Artifact, delivery.artifact_id)
    target = destination_for(db, delivery, share, artifact)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"somebody else's results")

    report = deliver_one(db, delivery.id, store=store)

    assert report.failed
    assert "will not overwrite" in (report.message or "")
    assert target.read_bytes() == b"somebody else's results"
    db.refresh(delivery)
    assert delivery.status == DeliveryStatus.FAILED.value


def test_its_own_previous_attempt_is_not_a_collision(db: Session, user, store, share):
    """A courier that died after copying and before recording must not then
    fail for finding its own work in place."""
    delivery = a_delivery(db, user, store)
    assert deliver_one(db, delivery.id, store=store).delivered

    delivery.status = DeliveryStatus.PENDING
    delivery.next_attempt_at = None
    db.flush()
    again = deliver_one(db, delivery.id, store=store)

    assert again.delivered


def test_a_copy_that_fails_leaves_nothing_behind_on_the_share(
    db: Session, user, store, share, monkeypatch
):
    """A forty-gigabyte copy that runs out of disk has already written most of
    a file onto somebody else's storage. Nothing else would ever remove it."""
    from app.application import deliveries as module

    def dies_halfway(source, destination, *args, **kwargs):
        pathlib.Path(destination).write_bytes(b"most of a file")
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(module.shutil, "copy2", dies_halfway)
    delivery = a_delivery(db, user, store)
    artifact = db.get(Artifact, delivery.artifact_id)
    target = destination_for(db, delivery, share, artifact)

    report = deliver_one(db, delivery.id, store=store)

    assert not report.delivered
    assert "No space left" in (report.message or "")
    assert not target.exists()
    assert list(target.parent.iterdir()) == []


def test_an_unwritable_root_fails_without_retrying(db: Session, user, store, share):
    share.writable = False
    db.flush()
    delivery = a_delivery(db, user, store)

    report = deliver_one(db, delivery.id, store=store)

    # Configuration, not weather: retrying changes nothing, and the message
    # names what an administrator has to do.
    assert report.failed
    assert "read-only" in (report.message or "")
    db.refresh(delivery)
    assert delivery.next_attempt_at is None


def test_a_withdrawn_root_is_refused(db: Session, user, store, share):
    share.revoked_at = datetime.now(UTC)
    share.writable = False
    db.flush()
    delivery = a_delivery(db, user, store)

    report = deliver_one(db, delivery.id, store=store)

    assert report.failed
    assert "withdrawn" in (report.message or "")


def test_an_unmounted_share_is_retried(db: Session, user, store, share, tmp_path):
    """A share that is not mounted now is usually mounted again later."""
    (tmp_path / "lab-share").rmdir()
    delivery = a_delivery(db, user, store)

    report = deliver_one(db, delivery.id, store=store, retry_seconds=60, max_attempts=5)

    assert not report.failed
    assert "not mounted" in (report.message or "")
    db.refresh(delivery)
    assert delivery.status == DeliveryStatus.PENDING.value
    assert delivery.attempts == 1
    assert delivery.next_attempt_at is not None


def test_retrying_gives_up_eventually(db: Session, user, store, share, tmp_path):
    (tmp_path / "lab-share").rmdir()
    delivery = a_delivery(db, user, store)

    for _ in range(3):
        delivery.next_attempt_at = None
        db.flush()
        report = deliver_one(db, delivery.id, store=store, max_attempts=3)

    assert report.failed
    assert "Given up after 3 attempts" in (report.message or "")
    db.refresh(delivery)
    assert delivery.status == DeliveryStatus.FAILED.value


def test_a_shared_delivery_cannot_exist_without_a_root(db: Session, user, store, share):
    """The refusal is the database's, which is better than the courier's.

    `_usable` still answers for a missing root, because the column is nullable
    and a courier should say something useful rather than raise — but the row
    it would have to read cannot be written.
    """
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError, match="shared_has_target_root"), db.begin_nested():
        a_delivery(db, user, store, root_id=None)


def test_a_purged_output_cannot_be_delivered(db: Session, user, store, share):
    delivery = a_delivery(db, user, store)
    db.execute(
        text("UPDATE artifacts SET purged_at = now(), deleted_at = now() WHERE id = :i"),
        {"i": delivery.artifact_id},
    )

    report = deliver_one(db, delivery.id, store=store)

    assert report.failed
    assert "no longer in the artifact store" in (report.message or "")


def test_only_due_deliveries_are_offered(db: Session, user, store, share):
    waiting = a_delivery(db, user, store)
    later = a_delivery(db, user, store)
    later.next_attempt_at = datetime.now(UTC) + timedelta(hours=1)
    db.flush()

    due = due_delivery_ids(db, now=datetime.now(UTC))

    assert waiting.id in due
    assert later.id not in due


def test_a_leased_delivery_is_not_offered_twice(db: Session, user, store, share, tmp_path):
    """The lease is `next_attempt_at`, pushed forward at claim time.

    Committed before the copy starts, because holding a row lock for the
    length of a forty-gigabyte copy is the mistake this avoids.
    """
    delivery = a_delivery(db, user, store)
    deliver_one(db, delivery.id, store=store, lease_seconds=3600)

    db.refresh(delivery)
    assert delivery.id not in due_delivery_ids(db, now=datetime.now(UTC))


def test_a_download_delivery_is_never_carried(db: Session, user, store, share):
    delivery = a_delivery(db, user, store)
    delivery.mode = DeliveryMode.DOWNLOAD
    db.flush()

    assert deliver_one(db, delivery.id, store=store).skipped
    assert delivery.id not in due_delivery_ids(db, now=datetime.now(UTC))


def test_a_failed_delivery_can_be_put_back(db: Session, user, store, share):
    delivery = a_delivery(db, user, store)
    share.writable = False
    db.flush()
    deliver_one(db, delivery.id, store=store)
    share.writable = True
    db.flush()

    retry_delivery(db, delivery)

    assert delivery.status == DeliveryStatus.PENDING.value
    assert delivery.id in due_delivery_ids(db, now=datetime.now(UTC))
    assert deliver_one(db, delivery.id, store=store).delivered


def test_a_delivered_output_is_not_retried(db: Session, user, store, share):
    delivery = a_delivery(db, user, store)
    deliver_one(db, delivery.id, store=store)

    with pytest.raises(DeliveryRefused):
        retry_delivery(db, delivery)


# --- the loop ---------------------------------------------------------------


def test_a_round_reports_what_it_did(engine):
    courier = Courier(engine, load_settings())
    assert isinstance(courier.round().summary(), str)


def test_a_stopped_courier_performs_no_rounds(engine):
    courier = Courier(engine, load_settings())
    courier._stopping.set()
    assert courier.run_forever() == 0


def test_the_loop_is_bounded(engine):
    courier = Courier(engine, load_settings())
    courier.interval = 0
    assert courier.run_forever(max_rounds=2) == 2


def test_one_bad_delivery_does_not_stop_the_others(engine, monkeypatch):
    """A share that makes one copy raise must not stop every other delivery."""
    from app.workers import courier as module

    bad, good = uuid.uuid4(), uuid.uuid4()
    monkeypatch.setattr(module, "due_delivery_ids", lambda *a, **k: [bad, good])

    seen: list[uuid.UUID] = []

    def flaky(_session, delivery_id, **_kwargs):
        seen.append(delivery_id)
        if delivery_id == bad:
            raise OSError("the share went away mid-copy")
        return module.DeliveryReport(delivery_id=delivery_id, delivered=True)

    monkeypatch.setattr(module, "deliver_one", flaky)
    report = Courier(engine, load_settings()).round()

    assert seen == [bad, good]
    assert report.errors == 1
    assert report.delivered == [str(good)]
