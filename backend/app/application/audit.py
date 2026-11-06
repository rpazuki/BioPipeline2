"""Who changed what.

`audit_events` has been in the schema since the base migration with nothing
writing to it. Everything it was for happened anyway: somebody published a
catalog entry, attested a storage root, installed a package, changed a
colleague's role — and the only record was the effect.

**A mutation's audit belongs in the mutation's transaction.** If the change
rolls back, the record of it must roll back too: an audit saying a root was
revoked when it was not is worse than one that is silent, because it is the
thing people will believe. This is the deliberate opposite of the artifact
*read* audit, where a refusal is recorded on a session of its own precisely
because the request it refused is about to roll back. The rule is the same
underneath: **the record has to share the fate of the thing it describes.**

Run submissions and status transitions are recorded by a database trigger,
including scheduled work and worker updates. Deletion requests and cleanup
outcomes retain their own records after resources leave the interface.

**It records the domain action, not the HTTP request.** `catalog.published` is
answerable a year later; `POST /api/v1/publications/{uuid}/publish` is a URL
whose meaning has to be reconstructed. The request id is kept beside it, so a
line here and a line in the server log can still be joined.

Request-driven mutations include the authenticated actor and request context;
background cleanup records the administrator who requested deletion.
"""

from __future__ import annotations

import ipaddress
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.db.models import AuditEvent

# The vocabulary, in one place. Actions are `noun.verb` in the past tense,
# because what an audit answers is what happened, not what somebody asked for.
USER_CREATED = "user.created"
USER_ROLE_CHANGED = "user.role_changed"
USER_DEACTIVATED = "user.deactivated"
USER_REACTIVATED = "user.reactivated"
USER_PASSWORD_RESET = "user.password_reset"
ROOT_REGISTERED = "storage_root.registered"
ROOT_REVOKED = "storage_root.revoked"
ROOT_REINSTATED = "storage_root.reinstated"
CATALOG_PUBLISHED = "catalog.published"
CATALOG_ARCHIVED = "catalog.archived"
PACKAGES_CHANGED = "environment.packages_changed"
ENVIRONMENT_CREATED = "environment.created"
ENVIRONMENT_DEFAULTED = "environment.made_default"
ENVIRONMENT_UNLOCKED = "environment.unlocked"


@dataclass(frozen=True, slots=True)
class RequestContext:
    """What the HTTP layer knows and the domain does not."""

    actor_id: uuid.UUID | None = None
    request_id: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None


def as_ip(value: str | None) -> str | None:
    """Only a real address reaches an `inet` column.

    A malformed peer would otherwise turn a successful mutation into a 500 —
    the audit taking down the thing it is auditing. Only the direct peer:
    honouring `X-Forwarded-For` without a configured list of trusted proxies
    would record whatever the client asked us to.
    """
    if not value:
        return None
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


def record(
    session: Session,
    *,
    action: str,
    target_type: str,
    target_id: uuid.UUID | None = None,
    context: RequestContext | None = None,
    project_id: uuid.UUID | None = None,
    **details: Any,
) -> AuditEvent:
    """Write down one change, in the transaction that made it.

    `details` is deliberately open: what is worth keeping differs per action —
    which package, which role, which root path — and a fixed shape would
    either be mostly null or force the interesting part into a string.
    """
    context = context or RequestContext()
    event = AuditEvent(
        project_id=project_id,
        actor_id=context.actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        ip_address=context.ip_address,
        user_agent=(context.user_agent or None),
        request_id=context.request_id,
        metadata_=details,
    )
    session.add(event)
    session.flush()
    return event


def recent(
    session: Session,
    *,
    limit: int = 100,
    action: str | None = None,
    target_type: str | None = None,
    actor_id: uuid.UUID | None = None,
    target_id: uuid.UUID | None = None,
    offset: int = 0,
) -> list[AuditEvent]:
    """The log, newest first.

    Filtered by the three questions people actually arrive with: what kind of
    thing changed, what happened to it, and who did it.
    """
    query = select(AuditEvent)
    if action:
        query = query.where(AuditEvent.action == action)
    if target_type:
        query = query.where(AuditEvent.target_type == target_type)
    if actor_id:
        query = query.where(AuditEvent.actor_id == actor_id)
    if target_id:
        query = query.where(AuditEvent.target_id == target_id)
    return list(
        session.execute(
            query.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
            .offset(offset)
            .limit(limit)
        ).scalars()
    )
