"""Administering accounts.

Until now the only way to add a researcher was to run `scripts/dev/seed.py` on
the server, which means a deployment could not take on a new person without
somebody with shell access. That is the same shape of gap storage roots had:
a table only SQL could reach.

**An administrator never chooses somebody else's password.** They create the
account and the platform generates one, shown to them exactly once to pass on.
`must_change_password` is what keeps that a one-time fact: until the person
sets their own, the only request their session may make is the one that
changes it. Without that flag an admin-created account is one an admin can go
on signing into for ever.

**Accounts are deactivated, never deleted.** A user owns runs, publications,
uploads and audit rows; deleting one would either cascade through the history
or be refused by the database. Deactivating ends their access immediately —
the session epoch sees to that — and leaves the record of what they did.

**The last administrator cannot be removed.** Not paternalism: there is no
recovery path that does not involve shell access to the database, which is
precisely what this screen exists to avoid needing.
"""

from __future__ import annotations

import secrets
import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.application.auth import hash_password
from app.domain.enums import UserRole
from app.domain.errors import Conflict, ValidationFailed
from app.infrastructure.db.models import User

# Long enough that it is not worth attacking in the hours before it is
# changed, short enough to be read down a phone line once.
GENERATED_LENGTH = 16
EMAIL_MAX = 320


class UserRejected(ValidationFailed):
    code = "user.invalid"


class EmailTaken(Conflict):
    code = "user.email_taken"


class LastAdministrator(Conflict):
    """The change would leave the deployment with no way back in."""

    code = "user.last_administrator"


def generate_password() -> str:
    """A password nobody chose and nobody has to remember.

    Shown once. It exists to get somebody through their first sign-in, and
    `must_change_password` guarantees that is all it can ever do.
    """
    return secrets.token_urlsafe(GENERATED_LENGTH)


def list_users(
    session: Session,
    *,
    include_inactive: bool = True,
    search: str | None = None,
    limit: int = 100,
) -> tuple[list[User], int]:
    """Accounts, with the total behind them.

    Paged like every other list in this API. A deployment has five to twenty
    people (ADR 0006), so this will almost always be one page — but an
    unbounded list query is an unbounded list query, and the development
    database is already eight thousand accounts deep in test leftovers, which
    is how this was noticed.
    """
    query = select(User)
    if not include_inactive:
        query = query.where(User.is_active.is_(True))
    if search:
        pattern = f"%{search.strip().lower()}%"
        query = query.where(
            func.lower(User.email).like(pattern) | func.lower(User.display_name).like(pattern)
        )
    total = int(session.execute(select(func.count()).select_from(query.subquery())).scalar_one())
    rows = list(
        session.execute(query.order_by(User.created_at.desc()).limit(min(limit, 500))).scalars()
    )
    return rows, total


def _active_admins(session: Session, *, excluding: uuid.UUID | None = None) -> int:
    query = select(func.count(User.id)).where(User.role == UserRole.ADMIN, User.is_active.is_(True))
    if excluding is not None:
        query = query.where(User.id != excluding)
    return int(session.execute(query).scalar_one())


def _clean_email(email: str) -> str:
    clean = (email or "").strip().lower()
    if "@" not in clean or len(clean) > EMAIL_MAX or " " in clean:
        raise UserRejected(f"'{email}' is not an email address.")
    return clean


def create(
    session: Session, *, email: str, display_name: str, role: str = UserRole.RESEARCHER
) -> tuple[User, str]:
    """Create an account and return it with its one-time password."""
    clean = _clean_email(email)
    name = (display_name or "").strip()
    if not name:
        raise UserRejected("A person needs a name to show.")
    if role not in {member.value for member in UserRole}:
        raise UserRejected(f"'{role}' is not a role this platform has.")

    password = generate_password()
    user = User(
        email=clean,
        display_name=name,
        password_hash=hash_password(password),
        role=role,
        must_change_password=True,
    )
    session.add(user)
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError as error:
        if "uq_users_email_lower" not in str(error.orig):
            raise
        raise EmailTaken(f"An account for {clean} already exists.") from error
    return user, password


def reset_password(session: Session, user: User) -> str:
    """Issue a new one-time password and end every session it had.

    For the ordinary case: somebody locked out, on the phone. The epoch bump
    is what makes it immediate — an attacker holding a live session does not
    get to keep it because the password changed.
    """
    password = generate_password()
    user.password_hash = hash_password(password)
    user.must_change_password = True
    user.session_epoch += 1
    user.failed_login_count = 0
    user.locked_until = None
    session.flush()
    return password


def set_role(session: Session, user: User, role: str) -> User:
    if role not in {member.value for member in UserRole}:
        raise UserRejected(f"'{role}' is not a role this platform has.")
    losing_last_admin = (
        user.role == UserRole.ADMIN
        and role != UserRole.ADMIN
        and _active_admins(session, excluding=user.id) == 0
    )
    if losing_last_admin:
        raise LastAdministrator(
            f"{user.display_name} is the only administrator left. Make somebody "
            "else an administrator first."
        )
    if user.role != role:
        user.role = role
        # A demoted user must not keep admin authority until their session
        # happens to expire.
        user.session_epoch += 1
        session.flush()
    return user


def set_active(session: Session, user: User, *, active: bool) -> User:
    losing_last_admin = (
        not active
        and user.role == UserRole.ADMIN
        and _active_admins(session, excluding=user.id) == 0
    )
    if losing_last_admin:
        raise LastAdministrator(
            f"{user.display_name} is the only administrator left, so this account "
            "cannot be deactivated."
        )
    if user.is_active != active:
        user.is_active = active
        # Ends every live session at once rather than when each expires.
        user.session_epoch += 1
        session.flush()
    return user


def complete_password_change(session: Session, user: User) -> None:
    """Clear the flag once somebody has chosen their own password."""
    if user.must_change_password:
        user.must_change_password = False
        session.flush()
