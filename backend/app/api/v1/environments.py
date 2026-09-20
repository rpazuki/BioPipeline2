"""Runtime environments over HTTP: what is installed, and installing it.

Admin-only throughout. An install runs a package manager as a service account
on the machine that runs everybody's work; it is not a preference.

**An install is synchronous, and that is a decision rather than an
oversight.** Building a generation can take minutes — a wheel that compiles
takes longer — and the honest alternatives are a job queue with a fifth
process to run it, or a request that holds a connection. On a single VM with
5-20 users (ADR 0006), installing a package is a thing an admin does
deliberately and waits for, and the environment lock means a second admin is
told what is happening rather than queued behind it. The operation row is
written and committed *before* the build starts, so a request that times out
in a browser still leaves a record of what was attempted.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, status

from app.api.deps import AdminUser, Audit, Config, CurrentUser, Db
from app.api.schemas import (
    CallableResponse,
    ChangePackagesRequest,
    CreateEnvironmentRequest,
    EnvironmentDetail,
    EnvironmentResponse,
    GenerationResponse,
    IntrospectionResponse,
    PackageOperationResponse,
    PackageResponse,
    Page,
)
from app.application import audit as audit_log
from app.application.environments import (
    change_packages,
    create_environment,
    current_generation,
    generations_of,
    history,
    list_environments,
    packages_of,
    release_lock,
    set_default,
)
from app.domain.packaging import describe_editables, is_reproducible
from app.infrastructure.db.models import EnvironmentGeneration, RuntimeEnvironment
from app.infrastructure.environments import BuildFailed, GenerationBuilder, introspect
from app.settings import Settings

router = APIRouter(prefix="/environments", tags=["environments"])


def _builder(settings: Settings) -> GenerationBuilder:
    return GenerationBuilder(
        image=settings.task_default_image,
        root=settings.environment_root,
        binary=settings.container_runtime,
        timeout_seconds=settings.environment_build_timeout_seconds,
    )


def _summary(
    environment: RuntimeEnvironment, generation: EnvironmentGeneration | None
) -> EnvironmentResponse:
    packages = packages_of(generation) if generation else []
    return EnvironmentResponse(
        id=environment.id,
        name=environment.name,
        description=environment.description,
        status=environment.status,
        is_default=environment.is_default,
        python_version=environment.python_version,
        current_generation_id=environment.current_generation_id,
        locked_reason=environment.locked_reason,
        package_count=len(packages),
        editable=bool(generation and generation.editable),
        created_at=environment.created_at,
    )


def _detail(
    environment: RuntimeEnvironment, generation: EnvironmentGeneration | None
) -> EnvironmentDetail:
    packages = packages_of(generation) if generation else []
    base = _summary(environment, generation)
    return EnvironmentDetail(
        **base.model_dump(),
        packages=[
            PackageResponse(
                name=package.name, version=package.version, editable_path=package.editable_path
            )
            for package in packages
        ],
        reproducible=is_reproducible(packages),
        reproducibility_note=describe_editables(packages),
    )


def _or_404(db: Db, environment_id: uuid.UUID) -> RuntimeEnvironment:
    environment = db.get(RuntimeEnvironment, environment_id)
    if environment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "environment.not_found", "message": "No such environment."},
        )
    return environment


@router.get("", response_model=Page[EnvironmentResponse])
def list_all(db: Db, _user: CurrentUser) -> Page[EnvironmentResponse]:
    """Every environment.

    Readable by any signed-in user, not just admins: "what can I call?" is a
    question an author asks constantly, and hiding the answer behind an admin
    role would make the authoring screen useless to the people using it.
    """
    environments = list_environments(db)
    return Page[EnvironmentResponse](
        items=[_summary(item, current_generation(db, item)) for item in environments],
        total=len(environments),
    )


@router.get("/{environment_id}", response_model=EnvironmentDetail)
def read(environment_id: uuid.UUID, db: Db, _user: CurrentUser) -> EnvironmentDetail:
    """What is installed, and whether a run using it could be reproduced."""
    environment = _or_404(db, environment_id)
    return _detail(environment, current_generation(db, environment))


@router.post("", response_model=EnvironmentDetail, status_code=status.HTTP_201_CREATED)
def create(
    payload: CreateEnvironmentRequest, db: Db, _admin: AdminUser, settings: Config, context: Audit
) -> EnvironmentDetail:
    """Create an environment and build its first, empty generation."""
    builder = _builder(settings)
    if not builder.available():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "environment.no_runtime",
                "message": (
                    "No container runtime is available on this host, so an environment "
                    "cannot be built."
                ),
            },
        )
    environment = create_environment(
        db,
        name=payload.name,
        description=payload.description,
        make_default=payload.make_default,
        builder=builder,
        image_ref=settings.task_default_image,
    )
    audit_log.record(
        db,
        action=audit_log.ENVIRONMENT_CREATED,
        target_type="environment",
        target_id=environment.id,
        context=context,
        name=environment.name,
    )
    return _detail(environment, current_generation(db, environment))


@router.post("/{environment_id}/packages", response_model=PackageOperationResponse)
def change(
    environment_id: uuid.UUID,
    payload: ChangePackagesRequest,
    db: Db,
    admin: AdminUser,
    settings: Config,
    context: Audit,
) -> PackageOperationResponse:
    """Install, upgrade or uninstall, by building the next generation.

    Work already running is untouched: it pinned a generation, and nothing
    mutates a generation (ADR 0028).
    """
    environment = _or_404(db, environment_id)
    result = change_packages(
        db,
        environment,
        operation=payload.operation,
        specifier=payload.specifier,
        builder=_builder(settings),
        actor_id=admin.user_id,
    )
    # Recorded whether or not it worked: "why does this fail now" is
    # answered as often by an install that did not happen as by one that did.
    audit_log.record(
        db,
        action=audit_log.PACKAGES_CHANGED,
        target_type="environment",
        target_id=environment_id,
        context=context,
        environment=environment.name,
        operation=payload.operation,
        specifier=payload.specifier,
        succeeded=result.succeeded,
        digest=result.digest,
    )
    record = next(item for item in history(db, environment_id, limit=1))
    return PackageOperationResponse(
        id=record.id,
        operation=record.operation,
        specifier=record.specifier,
        status=record.status,
        resulting_digest=record.resulting_digest,
        generation_id=record.generation_id,
        created_at=record.created_at,
        finished_at=record.finished_at,
        log=(result.log or record.log or "")[-8000:],
    )


@router.get("/{environment_id}/operations", response_model=Page[PackageOperationResponse])
def operations(
    environment_id: uuid.UUID, db: Db, _admin: AdminUser
) -> Page[PackageOperationResponse]:
    """Install history: provenance, not bookkeeping.

    It answers why a pipeline that worked last month fails today, which no
    package list alone can answer — including the installs that failed.
    """
    _or_404(db, environment_id)
    records = history(db, environment_id)
    return Page[PackageOperationResponse](
        items=[
            PackageOperationResponse(
                id=record.id,
                operation=record.operation,
                specifier=record.specifier,
                status=record.status,
                resulting_digest=record.resulting_digest,
                generation_id=record.generation_id,
                created_at=record.created_at,
                finished_at=record.finished_at,
                log=(record.log or "")[-4000:],
            )
            for record in records
        ],
        total=len(records),
    )


@router.get("/{environment_id}/generations", response_model=Page[GenerationResponse])
def generations(
    environment_id: uuid.UUID, db: Db, _admin: AdminUser, limit: int = 50
) -> Page[GenerationResponse]:
    """Every generation, newest first.

    Runs pin these, so they outlive installs: a generation whose directory the
    janitor has reclaimed still says what the runs that pinned it imported.
    """
    environment = _or_404(db, environment_id)
    items, total = generations_of(db, environment_id, limit=limit)
    return Page[GenerationResponse](
        items=[
            GenerationResponse(
                id=item.id,
                digest=item.digest,
                status=item.status,
                python_version=item.python_version,
                editable=item.editable,
                package_count=len(packages_of(item)),
                message=item.message,
                created_at=item.created_at,
                built_at=item.built_at,
                current=item.id == environment.current_generation_id,
                reclaimed_at=item.purged_at,
            )
            for item in items
        ],
        total=total,
    )


@router.post("/{environment_id}/unlock", response_model=EnvironmentResponse)
def unlock(
    environment_id: uuid.UUID, db: Db, _admin: AdminUser, context: Audit
) -> EnvironmentResponse:
    """Clear a lock a crashed build left behind.

    An administrator's call, because the platform cannot tell a dead build
    from a slow one — and the failure it fixes is every later install being
    refused by a build that is not running.
    """
    environment = _or_404(db, environment_id)
    release_lock(db, environment)
    audit_log.record(
        db,
        action=audit_log.ENVIRONMENT_UNLOCKED,
        target_type="environment",
        target_id=environment_id,
        context=context,
        name=environment.name,
    )
    return _summary(environment, current_generation(db, environment))


@router.post("/{environment_id}/default", response_model=EnvironmentResponse)
def make_default(
    environment_id: uuid.UUID, db: Db, _admin: AdminUser, context: Audit
) -> EnvironmentResponse:
    """Choose which environment new runs pin. Runs already submitted keep theirs."""
    environment = _or_404(db, environment_id)
    set_default(db, environment)
    audit_log.record(
        db,
        action=audit_log.ENVIRONMENT_DEFAULTED,
        target_type="environment",
        target_id=environment_id,
        context=context,
        name=environment.name,
    )
    return _summary(environment, current_generation(db, environment))


@router.get("/{environment_id}/callables", response_model=IntrospectionResponse)
def callables(
    environment_id: uuid.UUID,
    db: Db,
    _user: CurrentUser,
    settings: Config,
    module: str = "",
) -> IntrospectionResponse:
    """What an author can call: the modules installed, or one module's functions.

    Answered by importing inside the task container, because the answer
    depends on what is installed there and the API process has none of it.
    """
    environment = _or_404(db, environment_id)
    generation = current_generation(db, environment)
    if generation is None or generation.status != "ready":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "environment.not_ready",
                "message": f"'{environment.name}' has no built generation to inspect.",
            },
        )
    try:
        found = introspect(_builder(settings), Path(generation.generation_path), module)
    except BuildFailed as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": error.code, "message": error.message, "details": error.details},
        ) from error
    return IntrospectionResponse(
        module=found.get("module") or None,
        modules=[str(name) for name in found.get("modules", [])],
        callables=[
            CallableResponse(
                name=str(item.get("name", "")),
                signature=str(item.get("signature", "")),
                summary=str(item.get("summary", "")),
            )
            for item in found.get("callables", [])
        ],
    )
