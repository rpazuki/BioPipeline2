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

import uuid

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
    release_lock,
    runtime_mount,
)
from app.application.pipelines import create_revision
from app.application.runs import submit_run
from app.domain.packaging import SpecifierRejected
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
    assert len([item for item in generations_of(db, environment.id) if item.status == "ready"]) == 2


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
