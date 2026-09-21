"""The administrator's surface: accounts, the fleet, and what changed.

Three things a deployment could not do without shell access until now. Add a
person. See whether the workers are alive. Find out who published the entry
that started producing wrong results last Tuesday.

**Auditing is recorded here and nowhere else**, for the same reason
authorization is enforced only here: a rule applied in one layer cannot be
forgotten in another. Each handler records the *domain* action it performed —
`user.role_changed`, not `POST /admin/users/{uuid}/role` — in the same
transaction as the change, so a mutation that rolls back takes its own record
with it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.api.deps import AdminUser, Audit, Config, Db
from app.api.schemas import (
    AuditEventResponse,
    CreatedUserResponse,
    CreateUserRequest,
    MetricsResponse,
    Page,
    SetRoleRequest,
    UserResponse,
    WorkerResponse,
)
from app.application import audit as audit_log
from app.application import users as accounts
from app.application.metrics import snapshot
from app.domain.enums import TaskStatus, UserRole
from app.infrastructure.db.models import RunTask, User, Worker

router = APIRouter(prefix="/admin", tags=["administration"])


def _user(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=UserRole(user.role),
        is_active=user.is_active,
        must_change_password=user.must_change_password,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
    )


def _or_404(db: Db, user_id: uuid.UUID) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "user.not_found", "message": "No such account."},
        )
    return user


# --- accounts --------------------------------------------------------------


@router.get("/users", response_model=Page[UserResponse])
def list_users(
    db: Db, _admin: AdminUser, search: str | None = None, limit: int = 100
) -> Page[UserResponse]:
    """Accounts, newest first, including the deactivated.

    Deactivated ones are listed rather than hidden: "they left" and "there was
    never an account" are different answers, and only one of them means
    somebody still has to be told something.

    `total` is the count behind the page, not the length of it, so a screen
    can say how many there are rather than how many it happens to be showing.
    """
    people, total = accounts.list_users(db, search=search, limit=limit)
    return Page[UserResponse](items=[_user(person) for person in people], total=total)


@router.post("/users", response_model=CreatedUserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: CreateUserRequest, db: Db, _admin: AdminUser, context: Audit
) -> CreatedUserResponse:
    """Create an account and hand back its one-time password.

    The password is in this response and nowhere else. It is not stored, not
    logged, and not recoverable — a second one is issued by resetting.
    """
    user, password = accounts.create(
        db, email=payload.email, display_name=payload.display_name, role=payload.role
    )
    audit_log.record(
        db,
        action=audit_log.USER_CREATED,
        target_type="user",
        target_id=user.id,
        context=context,
        email=user.email,
        role=user.role,
    )
    return CreatedUserResponse(user=_user(user), one_time_password=password)


@router.post("/users/{user_id}/role", response_model=UserResponse)
def set_role(
    user_id: uuid.UUID, payload: SetRoleRequest, db: Db, _admin: AdminUser, context: Audit
) -> UserResponse:
    """Change what somebody may do, ending their sessions immediately.

    A demoted user must not keep admin authority until their session happens
    to expire.
    """
    user = _or_404(db, user_id)
    was = user.role
    accounts.set_role(db, user, payload.role)
    audit_log.record(
        db,
        action=audit_log.USER_ROLE_CHANGED,
        target_type="user",
        target_id=user.id,
        context=context,
        email=user.email,
        was=was,
        now=user.role,
    )
    return _user(user)


@router.post("/users/{user_id}/deactivate", response_model=UserResponse)
def deactivate(user_id: uuid.UUID, db: Db, _admin: AdminUser, context: Audit) -> UserResponse:
    """End somebody's access, keeping everything they did.

    Not a delete: they own runs, publications and audit rows, and the history
    is the thing worth keeping when somebody leaves.
    """
    user = _or_404(db, user_id)
    accounts.set_active(db, user, active=False)
    audit_log.record(
        db,
        action=audit_log.USER_DEACTIVATED,
        target_type="user",
        target_id=user.id,
        context=context,
        email=user.email,
    )
    return _user(user)


@router.post("/users/{user_id}/reactivate", response_model=UserResponse)
def reactivate(user_id: uuid.UUID, db: Db, _admin: AdminUser, context: Audit) -> UserResponse:
    user = _or_404(db, user_id)
    accounts.set_active(db, user, active=True)
    audit_log.record(
        db,
        action=audit_log.USER_REACTIVATED,
        target_type="user",
        target_id=user.id,
        context=context,
        email=user.email,
    )
    return _user(user)


@router.post("/users/{user_id}/reset-password", response_model=CreatedUserResponse)
def reset_password(
    user_id: uuid.UUID, db: Db, _admin: AdminUser, context: Audit
) -> CreatedUserResponse:
    """Issue a new one-time password for somebody who is locked out.

    Every session they had ends with it: an attacker holding a live one does
    not get to keep it because the password changed.
    """
    user = _or_404(db, user_id)
    password = accounts.reset_password(db, user)
    audit_log.record(
        db,
        action=audit_log.USER_PASSWORD_RESET,
        target_type="user",
        target_id=user.id,
        context=context,
        email=user.email,
    )
    return CreatedUserResponse(user=_user(user), one_time_password=password)


# --- the fleet -------------------------------------------------------------


@router.get("/metrics", response_model=MetricsResponse)
def metrics(db: Db, _admin: AdminUser, settings: Config) -> MetricsResponse:
    """What an operator would be woken for, as it is right now.

    Admin-only although it carries no personal data: queue depth, failure
    counts and free disk describe how a deployment is doing, and that is not
    something an unauthenticated caller should be able to profile.
    """
    reading = snapshot(
        db,
        # Shorter than the reaper's patience on purpose. The reaper declares
        # a worker dead and takes its work back; this is the earlier window,
        # where a worker has gone quiet and nobody has noticed yet.
        stale_after_seconds=max(settings.task_heartbeat_seconds * 3, 90),
        overdue_after_seconds=settings.scheduler_misfire_grace_seconds,
        artifact_root=settings.artifact_root,
        workspace_root=settings.workspace_root,
    )
    return MetricsResponse(**reading.as_dict())


@router.get("/workers", response_model=Page[WorkerResponse])
def list_workers(db: Db, _admin: AdminUser) -> Page[WorkerResponse]:
    """Which workers exist, and when each last said anything.

    The reaper declares a worker dead and requeues its tasks, which is the
    part that must not need a human. This is the part that does: a fleet
    quietly falling behind, or a worker that was never started at all, looks
    identical from a queue that is merely long.
    """
    now = datetime.now(UTC)
    workers = list(db.execute(select(Worker).order_by(Worker.id)).scalars())
    running: dict[str, int] = {
        str(worker_id): int(count)
        for worker_id, count in db.execute(
            select(RunTask.claimed_by, func.count(RunTask.id))
            .where(RunTask.status == TaskStatus.RUNNING)
            .group_by(RunTask.claimed_by)
        ).all()
        if worker_id
    }
    return Page[WorkerResponse](
        items=[
            WorkerResponse(
                id=worker.id,
                hostname=worker.hostname,
                version=worker.version,
                status=worker.status,
                capacity=worker.capacity,
                started_at=worker.started_at,
                last_heartbeat_at=worker.last_heartbeat_at,
                heartbeat_age_seconds=(now - worker.last_heartbeat_at).total_seconds(),
                running_tasks=int(running.get(worker.id, 0)),
            )
            for worker in workers
        ],
        total=len(workers),
    )


# --- what changed ----------------------------------------------------------


@router.get("/audit-events", response_model=Page[AuditEventResponse])
def audit_events(
    db: Db,
    _admin: AdminUser,
    limit: int = 100,
    action: str | None = None,
    target_type: str | None = None,
    actor_id: uuid.UUID | None = None,
) -> Page[AuditEventResponse]:
    """Who changed what, newest first.

    The actor's email is resolved here rather than stored on the row: an
    address can change, and a log that says who somebody *was* is harder to
    read than one that says who they are.
    """
    events = audit_log.recent(
        db, limit=min(limit, 500), action=action, target_type=target_type, actor_id=actor_id
    )
    actors = {
        user.id: user.email
        for user in db.execute(
            select(User).where(User.id.in_({event.actor_id for event in events if event.actor_id}))
        ).scalars()
    }
    return Page[AuditEventResponse](
        items=[
            AuditEventResponse(
                id=event.id,
                action=event.action,
                target_type=event.target_type,
                target_id=event.target_id,
                actor_id=event.actor_id,
                actor_email=actors.get(event.actor_id) if event.actor_id else None,
                request_id=event.request_id,
                ip_address=event.ip_address,
                details=event.metadata_ or {},
                created_at=event.created_at,
            )
            for event in events
        ],
        total=len(events),
    )
