"""Runtime environments: what a task can import, and what a run actually used.

In a generic Python executor, "what can I call?" *is* the authoring
experience — which is why document 09 promoted this out of an afterthought.
An admin installs `labUtils` and a pipeline can suddenly name
`labUtils.demo.run`; nothing else in the system makes that possible.

Four things this owns.

**An install never disturbs running work.** It builds the next generation out
of place and moves the environment's pointer when it succeeds (ADR 0028). A
task that has been running for two days keeps the generation it pinned. That
is the whole reason generations exist, and it is why the environment is
locked while a build runs rather than serialised at the database level: the
lock is what stops two admins building from the same parent and one of them
silently losing.

**A run records what it used.** `runs.environment_generation_id` is set at
submission, from the environment's current generation, and never re-read. A
run that started on Tuesday says Tuesday's package set even if somebody
installed something on Wednesday.

**A generation that cannot be reproduced says so.** An editable install is a
link to a working tree; the source behind it can change with nobody's
knowledge (G94). The generation is marked, and the mark travels to every run
that pins it, because a provenance record that quietly overstates itself is
worse than none.

**A generation nothing needs is reclaimed.** Immutability costs a full copy
per install, so a deployment that installs weekly grows weekly until
something removes the copies no run can still reach. The directory goes; the
row stays, because a run points at it for ever.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.application.pipelines import default_project_id
from app.domain.enums import RunStatus, RuntimeEnvironmentStatus
from app.domain.errors import Conflict, ValidationFailed
from app.domain.lifecycle import RUN_MACHINE
from app.domain.packaging import Package, check_specifier, describe_editables
from app.infrastructure.db.models import (
    EnvironmentGeneration,
    PackageOperation,
    Run,
    RuntimeEnvironment,
)
from app.infrastructure.environments import (
    BuildFailed,
    GenerationBuilder,
    OutsideRoot,
    remove_generation,
    site_packages_of,
)
from app.infrastructure.execution.docker import RuntimeMount

OPERATIONS = ("install", "uninstall", "upgrade")


class EnvironmentBusy(Conflict):
    """Another install is already building the next generation."""

    code = "environment.busy"


class EnvironmentRejected(ValidationFailed):
    code = "environment.invalid"


@dataclass(frozen=True, slots=True)
class InstallResult:
    operation_id: uuid.UUID
    succeeded: bool
    generation_id: uuid.UUID | None
    digest: str | None
    message: str | None
    log: str


# --- reading ---------------------------------------------------------------


def list_environments(session: Session) -> list[RuntimeEnvironment]:
    return list(
        session.execute(
            select(RuntimeEnvironment).order_by(
                RuntimeEnvironment.is_default.desc(), RuntimeEnvironment.name
            )
        ).scalars()
    )


def default_environment(session: Session) -> RuntimeEnvironment | None:
    """The environment a run pins when nothing says otherwise.

    None is an ordinary state, not an error: a deployment that has never
    installed anything runs tasks against the image alone, which is the
    runner and the standard library.
    """
    return session.execute(
        select(RuntimeEnvironment).where(RuntimeEnvironment.is_default.is_(True))
    ).scalar_one_or_none()


def current_generation(
    session: Session, environment: RuntimeEnvironment
) -> EnvironmentGeneration | None:
    if environment.current_generation_id is None:
        return None
    return session.get(EnvironmentGeneration, environment.current_generation_id)


def generations_of(
    session: Session, environment_id: uuid.UUID, *, limit: int = 50
) -> tuple[list[EnvironmentGeneration], int]:
    """Builds of one environment, newest first, with the total behind them.

    Bounded, because this list only ever grows: a generation's row outlives
    the directory it describes, so an environment installed into weekly for
    two years has a hundred of them and every one is a row this would
    otherwise render.
    """
    query = select(EnvironmentGeneration).where(
        EnvironmentGeneration.environment_id == environment_id
    )
    total = int(session.execute(select(func.count()).select_from(query.subquery())).scalar_one())
    # By when it was built, falling back to when the row appeared for one that
    # is still building. Not `created_at` alone: that is the transaction
    # timestamp, so two rows written by one transaction share it and a
    # time-ordered list of them comes out shuffled -- the same trap
    # `schedule_events` fell into.
    newest = func.coalesce(EnvironmentGeneration.built_at, EnvironmentGeneration.created_at)
    rows = list(session.execute(query.order_by(newest.desc()).limit(min(limit, 200))).scalars())
    return rows, total


def history(session: Session, environment_id: uuid.UUID, *, limit: int = 50):
    """Install history. Provenance, not bookkeeping.

    It answers why a pipeline that worked last month fails today, which is a
    question no package list alone can answer.
    """
    return list(
        session.execute(
            select(PackageOperation)
            .where(PackageOperation.environment_id == environment_id)
            .order_by(PackageOperation.created_at.desc())
            .limit(limit)
        ).scalars()
    )


# --- creating and changing -------------------------------------------------


def create_environment(
    session: Session,
    *,
    name: str,
    builder: GenerationBuilder,
    image_ref: str,
    description: str | None = None,
    make_default: bool | None = None,
) -> RuntimeEnvironment:
    """Create an environment and build its first, empty generation.

    Empty rather than seeded: what belongs in a lab's environment is the
    lab's decision, and guessing would put a version of pandas in front of
    somebody who wanted a different one.
    """
    clean = (name or "").strip()
    if not clean:
        raise EnvironmentRejected("An environment needs a name.")

    environment = RuntimeEnvironment(
        project_id=default_project_id(session),
        name=clean,
        description=description,
        venv_path="",
        image_ref=image_ref,
        status=RuntimeEnvironmentStatus.BUILDING,
        is_default=False,
    )
    session.add(environment)
    session.flush()

    generation = EnvironmentGeneration(
        environment_id=environment.id,
        digest="sha256:" + "0" * 64,
        generation_path="",
        status="building",
    )
    session.add(generation)
    session.flush()

    path = builder.path_for(environment.id, generation.id)
    try:
        builder.create(path)
        built = builder.finish(path)
    except BuildFailed as error:
        # The directory goes with the failure. A half-built virtualenv that no
        # row points at is disk nothing will ever reclaim: the janitor asks
        # rows what to remove, and this one is about to say it has no path.
        builder.discard(path)
        generation.status = "failed"
        generation.message = error.message
        environment.status = RuntimeEnvironmentStatus.FAILED
        session.flush()
        raise

    _record_built(generation, built)
    environment.venv_path = str(path)
    environment.python_version = built.python_version
    environment.current_generation_id = generation.id
    environment.status = RuntimeEnvironmentStatus.AVAILABLE
    if make_default or default_environment(session) is None:
        _make_default(session, environment)
    session.flush()
    return environment


def _make_default(session: Session, environment: RuntimeEnvironment) -> None:
    """One default per project, enforced by a partial unique index.

    Cleared first, because the index would refuse the second `true` before
    the first was cleared and the failure would read as a bug.
    """
    for other in list_environments(session):
        if other.id != environment.id and other.is_default:
            other.is_default = False
    session.flush()
    environment.is_default = True
    session.flush()


def set_default(session: Session, environment: RuntimeEnvironment) -> RuntimeEnvironment:
    if environment.status != RuntimeEnvironmentStatus.AVAILABLE.value:
        raise EnvironmentRejected(
            f"'{environment.name}' is {environment.status}, so it cannot be the default."
        )
    _make_default(session, environment)
    return environment


def change_packages(
    session: Session,
    environment: RuntimeEnvironment,
    *,
    operation: str,
    specifier: str,
    builder: GenerationBuilder,
    actor_id: uuid.UUID | None = None,
    commit: bool = True,
) -> InstallResult:
    """Build the next generation, and move the pointer if it works.

    The transaction is committed at three points rather than once at the end,
    and that is deliberate. A build takes minutes — sometimes many, when a
    wheel compiles — and holding a transaction open for it would be minutes
    of idle-in-transaction on every install. More than that: the lock, the
    operation row and the outcome each have to survive independently, because
    the whole value of the history is that it records installs that *failed*.
    """
    if operation not in OPERATIONS:
        raise EnvironmentRejected(f"'{operation}' is not an operation this platform knows.")
    clean = check_specifier(specifier)
    if environment.locked_at is not None:
        raise EnvironmentBusy(
            f"'{environment.name}' is busy: {environment.locked_reason or 'a build is running'}."
        )
    parent = current_generation(session, environment)
    if parent is None or parent.status != "ready":
        raise EnvironmentRejected(f"'{environment.name}' has no usable generation to build from.")

    record = PackageOperation(
        environment_id=environment.id,
        actor_id=actor_id,
        operation=operation,
        specifier=clean,
        status="running",
    )
    session.add(record)
    environment.locked_at = datetime.now(UTC)
    environment.locked_reason = f"{operation} {clean}"
    session.flush()
    if commit:
        # Committed before the build starts: the lock is what stops a second
        # admin building from the same parent, and a lock nobody else can see
        # is not a lock.
        session.commit()

    generation = EnvironmentGeneration(
        environment_id=environment.id,
        digest="sha256:" + "0" * 64,
        generation_path="",
        status="building",
    )
    session.add(generation)
    session.flush()
    path = builder.path_for(environment.id, generation.id)

    try:
        builder.copy(Path(parent.generation_path), path)
        if operation == "uninstall":
            log = builder.uninstall(path, clean)
        else:
            log = builder.install(path, clean, upgrade=operation == "upgrade")
        built = builder.finish(path, log=log)
    except BuildFailed as error:
        builder.discard(path)
        generation.status = "failed"
        generation.message = error.message
        record.status = "failed"
        record.log = str(error.details.get("log") or "")
        record.finished_at = datetime.now(UTC)
        _unlock(environment)
        session.flush()
        if commit:
            session.commit()
        return InstallResult(
            operation_id=record.id,
            succeeded=False,
            generation_id=None,
            digest=None,
            message=error.message,
            log=record.log or "",
        )
    except OSError as error:
        builder.discard(path)
        generation.status = "failed"
        generation.message = str(error)
        record.status = "failed"
        record.log = str(error)
        record.finished_at = datetime.now(UTC)
        _unlock(environment)
        session.flush()
        if commit:
            session.commit()
        return InstallResult(
            operation_id=record.id,
            succeeded=False,
            generation_id=None,
            digest=None,
            message=str(error),
            log=str(error),
        )

    existing = session.execute(
        select(EnvironmentGeneration).where(
            EnvironmentGeneration.environment_id == environment.id,
            EnvironmentGeneration.digest == built.digest,
            EnvironmentGeneration.status == "ready",
        )
    ).scalar_one_or_none()
    if existing is not None:
        # The same package set as one that already exists -- an uninstall of
        # something that was not there, a reinstall of the same version. Keep
        # the generation that exists and throw away the copy, or the disk
        # grows for every no-op.
        builder.discard(path)
        session.delete(generation)
        target = existing
    else:
        _record_built(generation, built)
        target = generation

    environment.current_generation_id = target.id
    environment.python_version = built.python_version
    environment.status = RuntimeEnvironmentStatus.AVAILABLE
    record.status = "succeeded"
    record.resulting_digest = built.digest
    record.generation_id = target.id
    record.log = built.log[-8000:]
    record.finished_at = datetime.now(UTC)
    _unlock(environment)
    session.flush()
    if commit:
        session.commit()

    return InstallResult(
        operation_id=record.id,
        succeeded=True,
        generation_id=target.id,
        digest=built.digest,
        message=describe_editables(built.packages),
        log=built.log,
    )


def _record_built(generation: EnvironmentGeneration, built: Any) -> None:
    generation.digest = built.digest
    generation.generation_path = str(built.path)
    generation.packages = {"items": [package.as_dict() for package in built.packages]}
    generation.python_version = built.python_version
    generation.editable = built.editable
    generation.status = "ready"
    generation.built_at = datetime.now(UTC)


def _unlock(environment: RuntimeEnvironment) -> None:
    environment.locked_at = None
    environment.locked_reason = None


def release_lock(session: Session, environment: RuntimeEnvironment) -> RuntimeEnvironment:
    """Clear a lock a crashed build left behind.

    The failure this exists for: a process dies between taking the lock and
    recording an outcome, and every later install is refused by a build that
    is not running. An administrator's decision, because the platform cannot
    tell a dead build from a slow one.
    """
    _unlock(environment)
    session.flush()
    return environment


# --- what a run used -------------------------------------------------------


def pin_for_run(session: Session) -> uuid.UUID | None:
    """The generation a run submitted now should record.

    Read once, at submission. Re-reading it later would mean a run's
    provenance changed after the fact, which is the opposite of provenance.
    """
    environment = default_environment(session)
    if environment is None:
        return None
    generation = current_generation(session, environment)
    if generation is None or generation.status != "ready":
        return None
    # Nothing is counted here. The run row *is* the reference, and it is
    # written by the transaction that submits the run, so it cannot be lost
    # by a process that dies later. See `reclaimable`.
    return generation.id


def packages_of(generation: EnvironmentGeneration) -> list[Package]:
    raw = (generation.packages or {}).get("items") or []
    return [Package.from_dict(item) for item in raw]


def generation_for_run(session: Session, run_id: uuid.UUID) -> EnvironmentGeneration | None:
    run = session.get(Run, run_id)
    if run is None or run.environment_generation_id is None:
        return None
    return session.get(EnvironmentGeneration, run.environment_generation_id)


def runtime_mount(session: Session, run_id: uuid.UUID) -> RuntimeMount | None:
    """Where this run's pinned generation is, and what to put on PYTHONPATH.

    None when the deployment has no environment, which is an ordinary state:
    tasks then run against the image alone -- the runner and the standard
    library.
    """
    generation = generation_for_run(session, run_id)
    if generation is None or generation.status != "ready" or not generation.generation_path:
        return None
    if generation.purged_at is not None:
        # Unreachable by construction -- the janitor never reclaims a
        # generation a live run pins -- and checked anyway, because the
        # alternative is a bind mount of a directory that is not there.
        # Docker would create it, empty, and the task would fail on an import
        # error that says nothing about why.
        return None
    return RuntimeMount(
        host_path=generation.generation_path,
        site_packages=site_packages_of(generation.generation_path, generation.python_version),
    )


# --- reclaiming ------------------------------------------------------------
#
# A generation is a full copy of the one before it, which is the price ADR
# 0028 paid for isolation that does not depend on filesystem features. A
# deployment that installs something every week grows by an environment every
# week unless something reclaims the ones nothing needs.
#
# What is reclaimed is the *directory*. The row stays for ever: a run points
# at it, and `packages` answers "what did that run import" long after the
# bytes are gone. Same shape as an artifact purge, same reason (ADR 0012).


# Every state a run can be in and still need what it pinned. Derived from the
# lifecycle machine rather than listed, so a new run state cannot silently
# become one the janitor treats as finished.
LIVE_RUN_STATUSES = tuple(
    status.value for status in RunStatus if not RUN_MACHINE.is_terminal(status.value)
)


@dataclass(frozen=True, slots=True)
class ReclaimReport:
    """What one pass reclaimed, and what it would not touch."""

    removed: int = 0
    already_gone: int = 0
    refused: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        return bool(self.removed or self.already_gone or self.refused)


def reclaimable(
    session: Session, *, grace_hours: int, limit: int = 20
) -> list[tuple[uuid.UUID, str]]:
    """Generations whose directory nothing needs any more.

    Four conditions, and each one is a way of being wrong:

    * **Not its environment's current generation.** That one is what the next
      run submitted will pin.
    * **No live run pinned it.** A run that is queued today may mount it in
      two days' time, and a run that is running may be three days into a
      task. The runs are the references; there is no counter to disagree
      with them.
    * **Built longer ago than the grace period.** Submission reads the
      pointer and commits the run a moment later. Within that moment the run
      row does not exist yet, so a janitor looking only at rows would see a
      generation nothing referenced. The grace period is longer than any
      submission, which closes the window without a lock.
    * **Not already reclaimed.**
    """
    rows = session.execute(
        text(
            """
            SELECT g.id, g.generation_path
            FROM environment_generations g
            JOIN runtime_environments e ON e.id = g.environment_id
            WHERE g.purged_at IS NULL
              AND g.generation_path <> ''
              AND g.built_at IS NOT NULL
              AND g.built_at < now() - make_interval(hours => :grace)
              AND (e.current_generation_id IS NULL OR e.current_generation_id <> g.id)
              AND NOT EXISTS (
                  SELECT 1 FROM runs r
                  WHERE r.environment_generation_id = g.id
                    AND r.status = ANY(:live)
              )
            ORDER BY g.built_at
            LIMIT :limit
            """
        ),
        {"grace": grace_hours, "live": list(LIVE_RUN_STATUSES), "limit": limit},
    ).all()
    return [(row.id, row.generation_path) for row in rows]


def reclaim(
    session: Session, *, root: Path | str, grace_hours: int, limit: int = 20
) -> ReclaimReport:
    """Remove the directories, then record that they are gone.

    Bytes first, then the row -- the same ordering as an artifact purge, for
    the same reason. A row that says reclaimed while the directory survives
    is a lie that leaks disk; bytes removed before the row is stamped merely
    means the next sweep finds nothing there and says so.

    A removal that fails leaves the row alone, so the next sweep tries again.
    That is the right way round for a disk that is full or a mount that is
    read-only: both are conditions that end, and neither should cost the
    record of what a run ran against.
    """
    removed = 0
    already_gone = 0
    refused: list[str] = []
    for generation_id, path in reclaimable(session, grace_hours=grace_hours, limit=limit):
        try:
            existed = remove_generation(path, root=root)
        except OutsideRoot:
            # Kept, and reported. A row pointing outside the environment root
            # is a fact somebody needs to know about, not a directory to
            # remove on the strength of the row that is already wrong.
            refused.append(path)
            continue
        except OSError:
            continue
        if existed:
            removed += 1
        else:
            already_gone += 1
        session.execute(
            text("UPDATE environment_generations SET purged_at = now() WHERE id = :i"),
            {"i": generation_id},
        )
    return ReclaimReport(removed=removed, already_gone=already_gone, refused=tuple(refused))
