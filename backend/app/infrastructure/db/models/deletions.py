"""Durable deletion requests and definition tombstones."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base, created_at, timestamp, uuid_fk, uuid_pk


class ResourceDeletion(Base):
    """Retain deletion identity and cleanup progress independently of its resource."""

    __tablename__ = "resource_deletions"
    __table_args__ = (
        UniqueConstraint("target_type", "target_key"),
        CheckConstraint("status IN ('pending', 'failed', 'complete')", name="status_valid"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_key: Mapped[str] = mapped_column(String(512), nullable=False)
    requested_by: Mapped[uuid.UUID] = uuid_fk("users.id")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'pending'")
    )
    details: Mapped[dict[str, Any]] = mapped_column(
        nullable=False, server_default=text("'{}'::jsonb")
    )
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()
    completed_at: Mapped[datetime | None] = timestamp()
