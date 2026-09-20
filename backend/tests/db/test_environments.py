"""Installing into an environment, and what a run records about it.

The four things document 09 asks Phase 6 to prove:

* an install during a running task does not affect it;
* a run records the package set it used;
* an editable install is detected and the run marked non-reproducible;
* an admin can search installed callables and read a signature.

The builds here are real — a virtualenv, in the real task image, through
Docker — because a generation that only exists as a mock proves nothing about
whether a virtualenv survives being copied, which is the whole mechanism.
"""

from __future__ import annotations

import shutil
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.application.environments import (
    EnvironmentBusy,
    change_packages,
    create_environment,
    current_generation,
    generation_for_run,
    generations_of,
    history,
    packages_of,
    pin_for_run,
    reclaim,
    reclaimable,
    release_lock,
    runtime_mount,
)
from app.application.pipelines import create_revision, default_project_id
from app.application.runs import submit_run
from app.domain.packaging import SpecifierRejected
from app.infrastructure.db.models import EnvironmentGeneration, RuntimeEnvironment
from app.infrastructure.environments import GenerationBuilder, introspect

pytestmark = pytest.mark.db

IMAGE = "biopipeline2/task-base:dev"

DOC = """
pipeline: __NAME__
defaults: {root: /d}
stages:
  - name: only
    steps:
      - {name: a, package: labUtils.x, method: run}
"""


@pytest.fixture
def builder(tmp_path) -> GenerationBuilder:
    made = GenerationBuilder(image=IMAGE, root=tmp_path / "environments", timeout_seconds=600)
    if not made.available():
        pytest.skip("no container runtime")
    return made


@pytest.fixture
def user(db: Session) -> uuid.UUID:
    return db.execute(
        text(
            "INSERT INTO users (email, display_name, role) VALUES (:e, 'E', 'admin') RETURNING id"
        ),
        {"e": f"env-{uuid.uuid4().hex[:10]}@example.org"},
    ).scalar_one()


@pytest.fixture
def environment(db: Session, builder, user):
    return create_environment(
        db,
        name=f"lab-{uuid.uuid4().hex[:8]}",
        builder=builder,
        image_ref=IMAGE,
        make_default=True,
    )


def a_run(db: Session, user: uuid.UUID):
    revision = create_revision(
        db, source_text=DOC.replace("__NAME__", f"env_{uuid.uuid4().hex[:8]}"), owner_id=user
    )
    return submit_run(db, pipeline_revision_id=revision.revision_id, requested_by=user, values={})


# --- building --------------------------------------------------------------


@pytest.mark.slow
def test_an_environment_starts_as_an_empty_virtualenv(db: Session, environment, builder):
    """Empty rather than seeded: what belongs in a lab's environment is the
    lab's decision."""
    generation = current_generation(db, environment)

    assert generation is not None
    assert generation.status == "ready"
    assert environment.python_version.startswith("3.")
    # pip and setuptools may be there; nothing anybody chose is.
    assert all(
        package.name.lower() in {"pip", "setuptools", "wheel"}
        for package in packages_of(generation)
    )
    # `pyvenv.cfg`, not `bin/python`: the interpreter is a symlink into the
    # image, so it dangles when read from the host and resolves in the
    # container. That asymmetry is exactly why a generation is only ever used
    # at the path it was built at.
    assert (builder.path_for(environment.id, generation.id) / "pyvenv.cfg").is_file()


@pytest.mark.slow
def test_installing_builds_a_new_generation_and_leaves_the_old_one(
    db: Session, environment, builder, user
):
    """The whole mechanism: a generation is never mutated, so a task that
    pinned the previous one goes on seeing exactly what it pinned."""
    before = current_generation(db, environment)
    assert before is not None

    result = change_packages(
        db,
        environment,
        operation="install",
        specifier="six==1.16.0",
        builder=builder,
        actor_id=user,
        commit=False,
    )

    assert result.succeeded, result.log
    after = current_generation(db, environment)
    assert after is not None and after.id != before.id
    assert "six" in {package.name.lower() for package in packages_of(after)}
    # The old generation is still there, still built, still usable.
    assert before.status == "ready"
    assert (builder.path_for(environment.id, before.id) / "pyvenv.cfg").is_file()
    assert "six" not in {package.name.lower() for package in packages_of(before)}


@pytest.mark.slow
def test_a_run_keeps_the_generation_it_pinned_when_a_later_install_lands(
    db: Session, environment, builder, user
):
    """Acceptance: an install during a running task does not affect it."""
    submitted = a_run(db, user)
    pinned = generation_for_run(db, submitted.run_id)
    assert pinned is not None

    change_packages(
        db,
        environment,
        operation="install",
        specifier="six==1.16.0",
        builder=builder,
        actor_id=user,
        commit=False,
    )
    db.expire(environment)

    # The environment moved on; the run did not.
    assert current_generation(db, environment).id != pinned.id
    assert generation_for_run(db, submitted.run_id).id == pinned.id
    mount = runtime_mount(db, submitted.run_id)
    assert mount is not None
    assert mount.host_path == pinned.generation_path
    assert mount.site_packages.startswith("/env/lib/python")


@pytest.mark.slow
def test_a_no_op_install_does_not_grow_the_disk(db: Session, environment, builder, user):
    """Two installs arriving at the same package set are the same generation."""
    change_packages(
        db,
        environment,
        operation="install",
        specifier="six==1.16.0",
        builder=builder,
        actor_id=user,
        commit=False,
    )
    first = current_generation(db, environment)

    change_packages(
        db,
        environment,
        operation="install",
        specifier="six==1.16.0",
        builder=builder,
        actor_id=user,
        commit=False,
    )
    db.expire(environment)

    assert current_generation(db, environment).id == first.id
    rows, total = generations_of(db, environment.id)
    assert total == 2
    assert len([item for item in rows if item.status == "ready"]) == 2


@pytest.mark.slow
def test_a_failed_install_is_recorded_with_pips_own_words(db: Session, environment, builder, user):
    """The history exists to answer why something fails, so it has to record
    the installs that failed."""
    before = current_generation(db, environment)

    result = change_packages(
        db,
        environment,
        operation="install",
        specifier="this-package-does-not-exist-9e7f",
        builder=builder,
        actor_id=user,
        commit=False,
    )

    assert not result.succeeded
    assert current_generation(db, environment).id == before.id
    record = history(db, environment.id)[0]
    assert record.status == "failed"
    assert "this-package-does-not-exist-9e7f" in record.specifier
    assert record.log
    # The environment is usable again immediately.
    assert environment.locked_at is None


@pytest.mark.slow
def test_an_admin_can_read_a_signature(db: Session, environment, builder):
    """Acceptance: search installed callables and read a signature.

    "What can I call?" is the authoring experience, and an author writing
    `package: x, method: y` is guessing without it.
    """
    change_packages(
        db,
        environment,
        operation="install",
        specifier="six==1.16.0",
        builder=builder,
        actor_id=None,
        commit=False,
    )
    generation = current_generation(db, environment)

    listed = introspect(builder, generation.generation_path)
    assert "six" in listed["modules"]

    inspected = introspect(builder, generation.generation_path, "six")
    names = {item["name"]: item for item in inspected["callables"]}
    assert "with_metaclass" in names
    assert names["with_metaclass"]["signature"].startswith("(")


# --- without a container ---------------------------------------------------


def test_a_second_install_is_refused_while_one_is_running(db: Session, user):
    """The lock is what stops two admins building from the same parent and one
    of them silently losing."""
    from app.application.pipelines import default_project_id
    from app.infrastructure.db.models import EnvironmentGeneration, RuntimeEnvironment

    environment = RuntimeEnvironment(
        project_id=default_project_id(db),
        name=f"busy-{uuid.uuid4().hex[:8]}",
        venv_path="/tmp/env",
        image_ref=IMAGE,
        status="available",
        locked_at=text("now()"),
    )
    db.add(environment)
    db.flush()
    generation = EnvironmentGeneration(
        environment_id=environment.id,
        digest="sha256:" + "a" * 64,
        generation_path="/tmp/env",
        status="ready",
    )
    db.add(generation)
    db.flush()
    environment.current_generation_id = generation.id
    environment.locked_reason = "install pandas"
    db.flush()

    with pytest.raises(EnvironmentBusy, match="install pandas"):
        change_packages(
            db,
            environment,
            operation="install",
            specifier="six",
            builder=GenerationBuilder(image=IMAGE, root="/tmp"),
            commit=False,
        )

    # And an admin can clear a lock a crashed build left behind.
    release_lock(db, environment)
    assert environment.locked_at is None


def test_a_specifier_that_is_not_a_package_never_reaches_pip(db: Session, user):
    from app.application.pipelines import default_project_id
    from app.infrastructure.db.models import RuntimeEnvironment

    environment = RuntimeEnvironment(
        project_id=default_project_id(db),
        name=f"safe-{uuid.uuid4().hex[:8]}",
        venv_path="/tmp/env",
        image_ref=IMAGE,
        status="available",
    )
    db.add(environment)
    db.flush()

    with pytest.raises(SpecifierRejected):
        change_packages(
            db,
            environment,
            operation="install",
            specifier="-e /srv/labUtils",
            builder=GenerationBuilder(image=IMAGE, root="/tmp"),
            commit=False,
        )


def test_a_deployment_with_no_environment_pins_nothing(db: Session, user):
    """An ordinary state: tasks run against the image alone."""
    db.execute(text("UPDATE runtime_environments SET is_default = false"))
    assert pin_for_run(db) is None
    submitted = a_run(db, user)
    assert generation_for_run(db, submitted.run_id) is None
    assert runtime_mount(db, submitted.run_id) is None


# --- reclaiming ------------------------------------------------------------
#
# Immutability costs a full copy per install. A deployment that installs
# every week grows by an environment every week unless something removes the
# copies nothing can still reach -- and "nothing can still reach" is a
# question about runs, which is why there is no counter to ask instead.


@pytest.fixture
def root(tmp_path) -> Path:
    return tmp_path / "environments"


def an_environment(db: Session) -> RuntimeEnvironment:
    environment = RuntimeEnvironment(
        project_id=default_project_id(db),
        name=f"gc-{uuid.uuid4().hex[:8]}",
        venv_path="",
        image_ref=IMAGE,
        status="available",
    )
    db.add(environment)
    db.flush()
    return environment


def a_generation(
    db: Session,
    environment: RuntimeEnvironment,
    root: Path,
    *,
    hours_ago: float = 48.0,
    current: bool = False,
) -> EnvironmentGeneration:
    """A generation on disk, without a container: the janitor never looks
    inside one, it only removes the directory the row names."""
    generation = EnvironmentGeneration(
        environment_id=environment.id,
        digest=f"sha256:{uuid.uuid4().hex}{uuid.uuid4().hex}",
        generation_path="",
        packages={"items": [{"name": "six", "version": "1.16.0"}]},
        python_version="3.12",
        status="ready",
        built_at=datetime.now(UTC) - timedelta(hours=hours_ago),
    )
    db.add(generation)
    db.flush()
    path = root / str(environment.id) / str(generation.id)
    (path / "lib").mkdir(parents=True)
    (path / "pyvenv.cfg").write_text("home = /usr/local/bin\n")
    generation.generation_path = str(path)
    if current:
        environment.current_generation_id = generation.id
    db.flush()
    return generation


def pinned_by(db: Session, generation: EnvironmentGeneration, run_id: uuid.UUID, status: str):
    db.execute(
        text("UPDATE runs SET environment_generation_id = :g, status = :s WHERE id = :r"),
        {"g": generation.id, "s": status, "r": run_id},
    )


def test_a_generation_nothing_can_reach_is_reclaimed(db: Session, user, root: Path):
    environment = an_environment(db)
    old = a_generation(db, environment, root)
    a_generation(db, environment, root, current=True)

    report = reclaim(db, root=root, grace_hours=24)

    assert report.removed == 1
    assert not Path(old.generation_path).exists()
    db.refresh(old)
    assert old.purged_at is not None


def test_what_a_run_imported_survives_the_bytes(db: Session, user, root: Path):
    """The row is not the disk. A run points at its generation for ever, and
    `packages` is the answer to what that run imported long after the
    directory holding them is gone (ADR 0012's distinction, applied here)."""
    environment = an_environment(db)
    generation = a_generation(db, environment, root)
    submitted = a_run(db, user)
    pinned_by(db, generation, submitted.run_id, "succeeded")

    reclaim(db, root=root, grace_hours=24)

    db.refresh(generation)
    assert generation.purged_at is not None
    assert [package.name for package in packages_of(generation)] == ["six"]
    assert generation_for_run(db, submitted.run_id).id == generation.id
    # And it is no longer something a run could be given.
    assert runtime_mount(db, submitted.run_id) is None


def test_the_generation_new_runs_pin_is_never_reclaimed(db: Session, user, root: Path):
    environment = an_environment(db)
    current = a_generation(db, environment, root, current=True)

    reclaim(db, root=root, grace_hours=24)

    db.refresh(current)
    assert current.purged_at is None
    assert Path(current.generation_path).is_dir()


@pytest.mark.parametrize("status", ["queued", "running", "blocked", "cancel_requested"])
def test_a_generation_a_live_run_pinned_is_left_alone(db: Session, user, root: Path, status: str):
    """A run queued today may mount it in two days' time, and a run that is
    running may be three days into a task."""
    environment = an_environment(db)
    generation = a_generation(db, environment, root)
    submitted = a_run(db, user)
    pinned_by(db, generation, submitted.run_id, status)

    assert generation.id not in [item for item, _ in reclaimable(db, grace_hours=24)]

    reclaim(db, root=root, grace_hours=24)
    db.refresh(generation)
    assert generation.purged_at is None
    assert Path(generation.generation_path).is_dir()


def test_a_generation_built_within_the_grace_period_is_left_alone(db: Session, user, root: Path):
    """Submission reads the pointer and commits the run a moment later. In
    that moment no row references the generation the run is about to pin, and
    a janitor looking only at rows would see one nothing needs."""
    environment = an_environment(db)
    fresh = a_generation(db, environment, root, hours_ago=1)

    reclaim(db, root=root, grace_hours=24)

    db.refresh(fresh)
    assert fresh.purged_at is None
    assert Path(fresh.generation_path).is_dir()


def test_a_path_outside_the_environment_root_is_refused(db: Session, user, root: Path, tmp_path):
    """The path comes out of a database row. A sweep that will remove
    whatever a row names is one edited column away from removing something
    that was never a generation."""
    elsewhere = tmp_path / "not-an-environment"
    elsewhere.mkdir()
    environment = an_environment(db)
    generation = a_generation(db, environment, root)
    generation.generation_path = str(elsewhere)
    db.flush()

    report = reclaim(db, root=root, grace_hours=24)

    assert report.refused == (str(elsewhere),)
    assert report.removed == 0
    assert elsewhere.is_dir()
    # And the row is untouched, so nothing claims disk was reclaimed.
    db.refresh(generation)
    assert generation.purged_at is None


def test_a_directory_already_gone_is_still_recorded(db: Session, user, root: Path):
    """A sweep interrupted between the removal and the update, or an operator
    who removed it by hand. Recording it is still correct."""
    environment = an_environment(db)
    generation = a_generation(db, environment, root)
    shutil.rmtree(generation.generation_path)

    report = reclaim(db, root=root, grace_hours=24)

    assert (report.removed, report.already_gone) == (0, 1)
    db.refresh(generation)
    assert generation.purged_at is not None


def test_reclaiming_is_idempotent(db: Session, user, root: Path):
    environment = an_environment(db)
    a_generation(db, environment, root)

    first = reclaim(db, root=root, grace_hours=24)
    second = reclaim(db, root=root, grace_hours=24)

    assert first.removed == 1
    assert not second.changed
