"""Type library and saved values."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.enums import LifecycleStatus
from app.infrastructure.db.base import (
    Base,
    created_at,
    enum_check,
    jsonb,
    status_column,
    updated_at,
    uuid_fk,
    uuid_pk,
)


class TypeDefinition(Base):
    __tablename__ = "type_definitions"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "key", "version", name="uq_type_definitions_project_id_key_version"
        ),
        enum_check("status", LifecycleStatus),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint(
            "source IN ('authored', 'imported_python', 'imported_legacy')",
            name="source_valid",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = uuid_fk("projects.id", index=True)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[int] = mapped_column(nullable=False)
    schema_: Mapped[dict[str, Any]] = mapped_column("schema", nullable=False)
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'authored'")
    )
    status: Mapped[str] = status_column(LifecycleStatus, LifecycleStatus.ACTIVE)
    created_by: Mapped[uuid.UUID] = uuid_fk("users.id")
    created_at: Mapped[datetime] = created_at()


class TypeDefinitionHead(Base):
    """Which version of a type is current.

    Doc 04 left ``saved_values.type_version`` nullable with no resolution rule
    (G33). Rather than a null meaning "latest, whatever that is now", the
    current version is an explicit row, and saved values always pin a version.
    """

    __tablename__ = "type_definition_heads"
    __table_args__ = (
        UniqueConstraint("project_id", "key", name="uq_type_definition_heads_project_id_key"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = uuid_fk("projects.id")
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    current_version: Mapped[int] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = updated_at()


class SavedValue(Base):
    __tablename__ = "saved_values"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "type_key", "name", name="uq_saved_values_user_id_type_key_name"
        ),
        # Always pinned: a saved value that silently re-interprets itself
        # against a new type version is a data-integrity bug (G33).
        ForeignKeyConstraint(
            ["project_id", "type_key", "type_version"],
            ["type_definitions.project_id", "type_definitions.key", "type_definitions.version"],
            name="fk_saved_values_type_definition",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = uuid_fk("projects.id")
    user_id: Mapped[uuid.UUID] = uuid_fk("users.id", ondelete="CASCADE", index=True)
    type_key: Mapped[str] = mapped_column(String(128), nullable=False)
    type_version: Mapped[int] = mapped_column(nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    value: Mapped[dict[str, Any]] = jsonb()
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()
