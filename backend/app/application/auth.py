"""Authentication: passwords, sessions, and the controls around them.

Opaque server-side sessions rather than tokens the client can read, matching
the current system. The cookie holds a random value; the database holds its
hash, so a leaked database does not hand over live sessions.

Three controls exist because the review found them missing, and each is cheap
compared with what it prevents:

* **Lockout.** Without it a weak password is a matter of patience.
* **A session epoch.** Changing a password or a role invalidates every
  outstanding session without a delete sweep, so a compromised session cannot
  outlive the response to it.
* **Sliding expiry with an idle timeout.** A session used daily stays alive;
  one abandoned on a shared machine does not.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.domain.enums import UserRole
from app.domain.errors import DomainError
from app.infrastructure.db.models import Session as SessionRow
from app.infrastructure.db.models import User

_hasher = PasswordHasher()

SESSION_TOKEN_BYTES = 32
MIN_PASSWORD_LENGTH = 12


class AuthenticationFailed(DomainError):
    """Wrong credentials, a locked account, or a dead session.

    Deliberately one error for all of them. Distinguishing "no such user" from
    "wrong password" tells an attacker which usernames exist.
    """

    code = "auth.failed"


class AccountLocked(DomainError):
    code = "auth.locked"


class PasswordTooWeak(DomainError):
    code = "auth.password_too_weak"


@dataclass(frozen=True, slots=True)
class Principal:
    """Who is making a request."""

    user_id: uuid.UUID
    email: str
    display_name: str
    role: str
    session_id: uuid.UUID
    # True while the account is on a password an administrator generated.
    must_change_password: bool = False

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN


def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordTooWeak(f"A password must be at least {MIN_PASSWORD_LENGTH} characters.")
    return _hasher.hash(password)


def _token_hash(token: str) -> str:
    """Hash a session token.

    SHA-256 rather than Argon2: the token is 256 bits of randomness, so there
    is nothing to brute-force, and this runs on every authenticated request.
    """
    return hashlib.sha256(token.encode()).hexdigest()


def create_user(
    db: DbSession,
    *,
    email: str,
    display_name: str,
    password: str,
    role: str = UserRole.RESEARCHER,
) -> uuid.UUID:
    user = User(
        email=email.strip(),
        display_name=display_name,
        password_hash=hash_password(password),
        role=role,
    )
    db.add(user)
    db.flush()
    return user.id


def authenticate(
    db: DbSession,
    *,
    email: str,
    password: str,
    lockout_threshold: int = 10,
    lockout_minutes: int = 15,
) -> User:
    """Verify credentials, or raise.

    Counts failures against the account and locks it for a window. The lock is
    on the account rather than the address, because an address is trivially
    changed and the thing being protected is the account.
    """
    user = db.execute(select(User).where(User.email == email.strip())).scalar_one_or_none()

    now = datetime.now(UTC)
    if user is None or not user.is_active or not user.password_hash:
        raise AuthenticationFailed("Those credentials are not valid.")
    if user.locked_until is not None and user.locked_until > now:
        raise AccountLocked("This account is temporarily locked after repeated failed sign-ins.")

    try:
        _hasher.verify(user.password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        # Recorded on its own connection, because the request that failed is
        # about to be rolled back and would take the counter with it. A
        # lockout that forgets every attempt is not a lockout.
        _record_failed_attempt(
            db,
            user_id=user.id,
            lockout_threshold=lockout_threshold,
            lockout_minutes=lockout_minutes,
        )
        raise AuthenticationFailed("Those credentials are not valid.") from None

    if _hasher.check_needs_rehash(user.password_hash):
        # Argon2 parameters change over time; rehashing on a successful verify
        # upgrades stored hashes without anyone having to reset a password.
        user.password_hash = _hasher.hash(password)
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    db.flush()
    return user


def _record_failed_attempt(
    db: DbSession, *, user_id: uuid.UUID, lockout_threshold: int, lockout_minutes: int
) -> None:
    """Count a failed sign-in so it survives the failing request.

    The authentication failure propagates out of the route, which rolls the
    request's transaction back. Writing the counter there would discard it, so
    the attempt is committed on a separate connection -- the same reasoning
    that applies to an audit record of a rejected action.
    """
    from sqlalchemy.orm import Session as NewSession

    bind = db.get_bind()
    with NewSession(bind=bind) as separate:
        target = separate.get(User, user_id)
        if target is None:
            return
        target.failed_login_count += 1
        if target.failed_login_count >= lockout_threshold:
            target.locked_until = datetime.now(UTC) + timedelta(minutes=lockout_minutes)
            target.failed_login_count = 0
        separate.commit()


def _as_ip(value: str | None) -> str | None:
    """Keep an address only if it really is one.

    The column is INET, and the value comes from a client or a proxy header.
    A malformed one is worth dropping rather than failing a sign-in over.
    """
    if not value:
        return None
    import ipaddress

    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


def start_session(
    db: DbSession,
    user: User,
    *,
    ttl_hours: int = 168,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> tuple[str, SessionRow]:
    """Create a session and return its token. The token is never stored."""
    token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
    row = SessionRow(
        user_id=user.id,
        token_hash=_token_hash(token),
        session_epoch=user.session_epoch,
        expires_at=datetime.now(UTC) + timedelta(hours=ttl_hours),
        ip_address=_as_ip(ip_address),
        user_agent=(user_agent or "")[:512] or None,
    )
    db.add(row)
    db.flush()
    return token, row


def resolve_session(
    db: DbSession,
    token: str,
    *,
    idle_timeout_hours: int = 24,
    ttl_hours: int = 168,
) -> Principal:
    """Turn a token into a principal, or raise.

    Renews the session on use, so an active session does not expire under
    somebody mid-task, while an idle one still does.
    """
    row = db.execute(
        select(SessionRow).where(SessionRow.token_hash == _token_hash(token))
    ).scalar_one_or_none()
    if row is None:
        raise AuthenticationFailed("This session is not valid.")

    now = datetime.now(UTC)
    if row.revoked_at is not None or row.expires_at <= now:
        raise AuthenticationFailed("This session has expired.")
    if row.last_seen_at + timedelta(hours=idle_timeout_hours) < now:
        raise AuthenticationFailed("This session has been idle too long.")

    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        raise AuthenticationFailed("This session is not valid.")
    if user.session_epoch != row.session_epoch:
        # The password or role changed after this session began.
        raise AuthenticationFailed("This session is no longer valid.")

    row.last_seen_at = now
    row.expires_at = now + timedelta(hours=ttl_hours)
    db.flush()
    return Principal(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        session_id=row.id,
        must_change_password=user.must_change_password,
    )


def end_session(db: DbSession, session_id: uuid.UUID) -> None:
    row = db.get(SessionRow, session_id)
    if row is not None and row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)
        db.flush()


def change_password(db: DbSession, user_id: uuid.UUID, *, current: str, replacement: str) -> None:
    """Change a password and invalidate every session it authorised.

    Bumping the epoch is what makes that immediate: a session whose epoch no
    longer matches is refused on its next request, without a sweep.
    """
    user = db.get(User, user_id)
    if user is None or not user.password_hash:
        raise AuthenticationFailed("Those credentials are not valid.")
    try:
        _hasher.verify(user.password_hash, current)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        raise AuthenticationFailed("Those credentials are not valid.") from None
    user.password_hash = hash_password(replacement)
    user.session_epoch += 1
    # Whatever it was before, the password is now theirs.
    user.must_change_password = False
    db.flush()


def set_role(db: DbSession, user_id: uuid.UUID, role: str) -> None:
    """Change a role, invalidating outstanding sessions.

    A demoted user must not keep admin authority until their session happens
    to expire.
    """
    user = db.get(User, user_id)
    if user is None:
        raise AuthenticationFailed("No such user.")
    if user.role != role:
        user.role = role
        user.session_epoch += 1
        db.flush()
