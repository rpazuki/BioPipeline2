"""Publication catalog: the curated researcher-facing contract."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.enums import FieldVisibility, PrimitiveType, PublicationStatus
from app.infrastructure.db.base import (
    Base,
    created_at,
    enum_check,
    jsonb,
    slug_check,
    slug_column,
    status_column,
    updated_at,
    uuid_fk,
    uuid_pk,
)


class Publication(Base):
    __tablename__ = "publications"
    __table_args__ = (
        UniqueConstraint("project_id", "slug", name="uq_publications_project_id_slug"),
        slug_check(),
        enum_check("status", PublicationStatus),
        # A published entry must point at a revision; a draft need not.
        CheckConstraint(
            "status <> 'published' OR current_revision_id IS NOT NULL",
            name="published_has_revision",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = uuid_fk("projects.id", index=True)
    slug: Mapped[str] = slug_column()
    # Mutable by design: changing it never affects existing runs, which point
    # at their own publication revision (doc 03 review addition). The FK was
    # missing in doc 04 (G31); a migration-level trigger also checks that the
    # revision belongs to this publication.
    current_revision_id: Mapped[uuid.UUID | None] = uuid_fk(
        "publication_revisions.id", nullable=True, use_alter=True
    )
    status: Mapped[str] = status_column(PublicationStatus, PublicationStatus.DRAFT)
    created_by: Mapped[uuid.UUID] = uuid_fk("users.id")
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class PublicationRevision(Base):
    __tablename__ = "publication_revisions"
    __table_args__ = (
        UniqueConstraint(
            "publication_id", "version", name="uq_publication_revisions_publication_id_version"
        ),
        CheckConstraint("version > 0", name="version_positive"),
        # Catalog search (G38). Document 07 specifies search and filtering
        # over the catalog and nothing in the plan's index list supported it.
        Index(
            "ix_publication_revisions_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
        Index(
            "ix_publication_revisions_description_trgm",
            "description",
            postgresql_using="gin",
            postgresql_ops={"description": "gin_trgm_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    publication_id: Mapped[uuid.UUID] = uuid_fk("publications.id", index=True)
    pipeline_revision_id: Mapped[uuid.UUID] = uuid_fk("pipeline_revisions.id", index=True)
    version: Mapped[int] = mapped_column(nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    display_metadata: Mapped[dict[str, Any]] = jsonb()
    access_policy: Mapped[dict[str, Any]] = jsonb()
    created_by: Mapped[uuid.UUID] = uuid_fk("users.id")
    created_at: Mapped[datetime] = created_at()


class PublicationField(Base):
    """UI and policy metadata for one public input or output declaration.

    Carries no YAML path binding: binding lives in the compiled pipeline IR.
    That separation is the point of the redesign (doc 01, drift 3).
    """

    __tablename__ = "publication_fields"
    __table_args__ = (
        UniqueConstraint(
            "publication_revision_id",
            "key",
            name="uq_publication_fields_publication_revision_id_key",
        ),
        enum_check("field_type", PrimitiveType),
        enum_check("visibility", FieldVisibility),
        # Exactly one of the two references must be set (G31). Without this a
        # field can dangle, or claim to be both an input and an output.
        CheckConstraint(
            "num_nonnulls(pipeline_input_id, pipeline_output_id) = 1",
            name="exactly_one_reference",
        ),
        # A fixed value the researcher can also edit is a contradiction (G31).
        CheckConstraint(
            "fixed_value IS NULL OR visibility = 'hidden'",
            name="fixed_value_is_hidden",
        ),
        # Catalog form rendering reads fields in order (doc 04 index list).
        Index(
            "ix_publication_fields_publication_revision_id_order_index",
            "publication_revision_id",
            "order_index",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    publication_revision_id: Mapped[uuid.UUID] = uuid_fk(
        "publication_revisions.id", ondelete="CASCADE"
    )
    pipeline_input_id: Mapped[uuid.UUID | None] = uuid_fk("pipeline_inputs.id", nullable=True)
    pipeline_output_id: Mapped[uuid.UUID | None] = uuid_fk("pipeline_outputs.id", nullable=True)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    label: Mapped[str] = mapped_column(String(256), nullable=False)
    help_text: Mapped[str | None] = mapped_column(Text)
    placeholder: Mapped[str | None] = mapped_column(String(256))
    field_type: Mapped[str] = status_column(PrimitiveType)
    type_ref: Mapped[str | None] = mapped_column(String(128))
    required: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    order_index: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))
    ui_group: Mapped[str | None] = mapped_column(String(128))
    default_value: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    fixed_value: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    constraints: Mapped[dict[str, Any]] = jsonb()
    # Narrows the pipeline input's source policy; may not widen it.
    source_policy: Mapped[dict[str, Any]] = jsonb()
    # Narrows the pipeline output's delivery modes (G16).
    delivery_policy: Mapped[dict[str, Any]] = jsonb()
    save_policy: Mapped[dict[str, Any]] = jsonb()
    visibility: Mapped[str] = status_column(FieldVisibility, FieldVisibility.VISIBLE)
