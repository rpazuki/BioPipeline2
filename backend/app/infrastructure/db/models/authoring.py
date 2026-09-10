"""Pipeline and workflow authoring.

Revision tables are immutable once written. That is enforced at the database
level by a trigger created in the base migration, not by convention (G23).
"""

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

from app.domain.enums import (
    ArtifactKind,
    LifecycleStatus,
    PrimitiveType,
    SourceFormat,
    ValidationStatus,
    Visibility,
)
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

IR_VERSION = "1.0"
"""Version of the compiled workflow intermediate representation (G22).

Stored on every workflow revision so a later release can tell whether it is
able to execute a revision compiled by an earlier one. A run never recompiles;
compatibility is a read-side decision.
"""


class PipelineDefinition(Base):
    __tablename__ = "pipeline_definitions"
    __table_args__ = (
        UniqueConstraint("project_id", "slug", name="uq_pipeline_definitions_project_id_slug"),
        slug_check(),
        enum_check("status", LifecycleStatus),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = uuid_fk("projects.id", index=True)
    slug: Mapped[str] = slug_column()
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[uuid.UUID] = uuid_fk("users.id")
    status: Mapped[str] = status_column(LifecycleStatus, LifecycleStatus.DRAFT)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class PipelineRevision(Base):
    """Immutable validated version of a pipeline definition."""

    __tablename__ = "pipeline_revisions"
    __table_args__ = (
        UniqueConstraint(
            "pipeline_id", "version", name="uq_pipeline_revisions_pipeline_id_version"
        ),
        CheckConstraint("version > 0", name="version_positive"),
        enum_check("source_format", SourceFormat),
        enum_check("validation_status", ValidationStatus),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    pipeline_id: Mapped[uuid.UUID] = uuid_fk("pipeline_definitions.id", index=True)
    version: Mapped[int] = mapped_column(nullable=False)
    source_format: Mapped[str] = status_column(SourceFormat, SourceFormat.YAML)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_spec: Mapped[dict[str, Any]] = jsonb()
    validation_status: Mapped[str] = status_column(ValidationStatus, ValidationStatus.PENDING)
    validation_report: Mapped[dict[str, Any]] = jsonb()
    created_by: Mapped[uuid.UUID] = uuid_fk("users.id")
    created_at: Mapped[datetime] = created_at()


class WorkflowTemplate(Base):
    __tablename__ = "workflow_templates"
    __table_args__ = (
        UniqueConstraint("project_id", "slug", name="uq_workflow_templates_project_id_slug"),
        slug_check(),
        enum_check("status", LifecycleStatus),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = uuid_fk("projects.id", index=True)
    slug: Mapped[str] = slug_column()
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[uuid.UUID] = uuid_fk("users.id")
    status: Mapped[str] = status_column(LifecycleStatus, LifecycleStatus.DRAFT)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class WorkflowRevision(Base):
    """Immutable compiled workflow. This is what a run points at."""

    __tablename__ = "workflow_revisions"
    __table_args__ = (
        UniqueConstraint(
            "workflow_id", "version", name="uq_workflow_revisions_workflow_id_version"
        ),
        CheckConstraint("version > 0", name="version_positive"),
        enum_check("source_format", SourceFormat),
        enum_check("validation_status", ValidationStatus),
        # Compilation is deterministic, so the same source must yield the same
        # hash. Indexed to let the compiler short-circuit an identical rebuild.
        Index("ix_workflow_revisions_graph_hash", "graph_hash"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    workflow_id: Mapped[uuid.UUID] = uuid_fk("workflow_templates.id", index=True)
    version: Mapped[int] = mapped_column(nullable=False)
    source_format: Mapped[str] = status_column(SourceFormat, SourceFormat.YAML)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    ir_version: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text(f"'{IR_VERSION}'")
    )
    compiled_spec: Mapped[dict[str, Any]] = jsonb()
    input_schema: Mapped[dict[str, Any]] = jsonb()
    output_schema: Mapped[dict[str, Any]] = jsonb()
    graph_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    validation_status: Mapped[str] = status_column(ValidationStatus, ValidationStatus.PENDING)
    validation_report: Mapped[dict[str, Any]] = jsonb()
    # Null means "whatever the deployment default is at run time"; a value
    # pins execution to one image so provenance survives an image bump.
    runtime_environment_id: Mapped[uuid.UUID | None] = uuid_fk(
        "runtime_environments.id", nullable=True
    )
    created_by: Mapped[uuid.UUID] = uuid_fk("users.id")
    created_at: Mapped[datetime] = created_at()


class WorkflowInput(Base):
    """Normalised copy of one input from the compiled spec, for querying."""

    __tablename__ = "workflow_inputs"
    __table_args__ = (
        UniqueConstraint(
            "workflow_revision_id", "key", name="uq_workflow_inputs_workflow_revision_id_key"
        ),
        enum_check("primitive_type", PrimitiveType),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    workflow_revision_id: Mapped[uuid.UUID] = uuid_fk(
        "workflow_revisions.id", ondelete="CASCADE", index=True
    )
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    type_ref: Mapped[str | None] = mapped_column(String(128))
    primitive_type: Mapped[str] = status_column(PrimitiveType)
    required: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    default_value: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    constraints: Mapped[dict[str, Any]] = jsonb()
    # {"modes": ["upload", "shared", "url"], "shared_roots": [...], ...}
    source_policy: Mapped[dict[str, Any]] = jsonb()


class WorkflowOutput(Base):
    __tablename__ = "workflow_outputs"
    __table_args__ = (
        UniqueConstraint(
            "workflow_revision_id", "key", name="uq_workflow_outputs_workflow_revision_id_key"
        ),
        enum_check("artifact_kind", ArtifactKind),
        enum_check("visibility", Visibility),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    workflow_revision_id: Mapped[uuid.UUID] = uuid_fk(
        "workflow_revisions.id", ondelete="CASCADE", index=True
    )
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    artifact_kind: Mapped[str] = status_column(ArtifactKind, ArtifactKind.TASK_OUTPUT)
    visibility: Mapped[str] = status_column(Visibility, Visibility.PRIVATE)
    # Which destinations this output may be delivered to (G16), e.g.
    # ["download", "shared"]. Narrowed further by the publication.
    delivery_modes: Mapped[dict[str, Any]] = jsonb(default="'[]'::jsonb")
    retention_policy: Mapped[dict[str, Any]] = jsonb()
