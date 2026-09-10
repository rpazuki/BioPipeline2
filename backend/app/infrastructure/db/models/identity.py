"""Users, sessions, and projects."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import INET, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.enums import LifecycleStatus, ProjectRole, UserRole
from app.infrastructure.db.base import (
    Base,
    created_at,
    enum_check,
    slug_check,
    slug_column,
    status_column,
    timestamp,
    updated_at,
    uuid_fk,
    uuid_pk,
)


class Project(Base):
    """Tenancy container.

    ADR 0009 is open. This build implements the recommended option: the table
    exists from the first migration and every owned entity carries
    ``project_id``, with one default project seeded (G29). Adding the column
    later is a migration across every large table; leaving it unused costs a
    few bytes a row.
    """

    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_projects_slug"),
        slug_check(),
        enum_check("status", LifecycleStatus),
        # Exactly one project may be the default, so code that resolves "the
        # project" in a single-project deployment cannot pick the wrong row.
        Index(
            "uq_projects_is_default",
            "is_default",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    slug: Mapped[str] = slug_column()
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = status_column(LifecycleStatus, LifecycleStatus.ACTIVE)
    is_default: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        # Case-insensitive uniqueness. A functional index rather than the
        # citext extension, which is not installable in every environment.
        Index("uq_users_email_lower", text("lower(email)"), unique=True),
        enum_check("role", UserRole),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    # Null when the account is provisioned for an external identity provider
    # only. ADR 0007 (SSO at launch) is open; the column supports either.
    password_hash: Mapped[str | None] = mapped_column(Text)
    auth_provider: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=text("'local'")
    )
    external_subject: Mapped[str | None] = mapped_column(String(256))
    role: Mapped[str] = status_column(UserRole, UserRole.RESEARCHER)
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    # Bumped on password change and role change, which invalidates every
    # outstanding session without a delete sweep (G45).
    session_epoch: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))
    failed_login_count: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))
    locked_until: Mapped[datetime | None] = timestamp()
    last_login_at: Mapped[datetime | None] = timestamp()
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = (enum_check("role", ProjectRole),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role: Mapped[str] = status_column(ProjectRole, ProjectRole.MEMBER)
    created_at: Mapped[datetime] = created_at()


class Session(Base):
    """Opaque server-side session, matching the current system's model."""

    __tablename__ = "sessions"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_sessions_token_hash"),
        # Cheap pruning of dead sessions (G38).
        Index("ix_sessions_expires_at", "expires_at"),
        Index("ix_sessions_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = uuid_fk("users.id", ondelete="CASCADE")
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    # Must match users.session_epoch or the session is dead (G45).
    session_epoch: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))
    # The current system renews sessions on use; without this column that
    # behaviour cannot be expressed at all (G32).
    last_seen_at: Mapped[datetime] = created_at()
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    revoked_at: Mapped[datetime | None] = timestamp()
    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = created_at()
