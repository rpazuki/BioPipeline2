"""Type library and saved values."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, Index, String, UniqueConstraint, text
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
        # No version: the real type library has none. A type is frozen where it
        # is used, by the `type_schema` snapshot on the publication field and
        # the saved value.
        UniqueConstraint("project_id", "key", name="uq_type_definitions_project_id_key"),
        enum_check("status", LifecycleStatus),
        CheckConstraint(
            "source IN ('authored', 'imported_python', 'imported_legacy')",
            name="source_valid",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = uuid_fk("projects.id", index=True)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    schema_: Mapped[dict[str, Any]] = mapped_column("schema", nullable=False)
    description: Mapped[str | None] = mapped_column(String(1024))
    # The Python class this type was imported from, e.g.
    # "labUtils.media_bot.CustomReplicateRule". Enables round-tripping to
    # dataclasses, TypedDict and Pydantic models.
    source_ref: Mapped[str | None] = mapped_column(String(512))
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'authored'")
    )
    status: Mapped[str] = status_column(LifecycleStatus, LifecycleStatus.ACTIVE)
    created_by: Mapped[uuid.UUID] = uuid_fk("users.id")
    created_at: Mapped[datetime] = created_at()


class SavedValue(Base):
    __tablename__ = "saved_values"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "type_key",
            "container",
            "name",
            name="uq_saved_values_user_id_type_key_container_name",
        ),
        CheckConstraint("container IN ('single', 'list', 'map')", name="container_valid"),
        Index("ix_saved_values_type_key", "type_key"),
        # No version pin. The real type library has no versioning at all;
        # a value is frozen by the `type_schema` snapshot stored alongside it,
        # which is also how the current system does it. An FK to a version
        # would invent a lifecycle the types do not have.
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = uuid_fk("projects.id")
    user_id: Mapped[uuid.UUID] = uuid_fk("users.id", ondelete="CASCADE", index=True)
    type_key: Mapped[str] = mapped_column(String(128), nullable=False)
    # The resolved schema as it stood when the value was saved. This is what
    # freezes the type, and it survives the definition changing later.
    type_schema: Mapped[dict[str, Any]] = jsonb()
    container: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'single'")
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    value: Mapped[dict[str, Any]] = jsonb()
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()
