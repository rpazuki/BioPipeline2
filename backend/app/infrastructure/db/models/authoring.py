"""Pipeline authoring.

One authoring level, not two. The current system separates a pipeline (a graph
of Python function calls) from a job definition (stages, dependencies, matrix
expansion, fan-out); BioPipeline2 collapses them into a single ``Pipeline``
whose revisions are immutable and directly runnable.

"Pipeline" rather than "Workflow": with one level there is no ambiguity left
to escape, and it is the word the lab already uses.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, Index, String, Text, UniqueConstraint, text
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
"""Version of the compiled intermediate representation (G22).

Stored on every revision so a later release can tell whether it can execute a
revision compiled by an earlier one. A run never recompiles; compatibility is
a read-side decision.
"""


class Pipeline(Base):
    """A mutable authoring container. Its revisions are what run."""

    __tablename__ = "pipelines"
    __table_args__ = (
        UniqueConstraint("project_id", "slug", name="uq_pipelines_project_id_slug"),
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
    """An immutable compiled pipeline. This is what a run points at."""

    __tablename__ = "pipeline_revisions"
    __table_args__ = (
        UniqueConstraint(
            "pipeline_id", "version", name="uq_pipeline_revisions_pipeline_id_version"
        ),
        CheckConstraint("version > 0", name="version_positive"),
        enum_check("source_format", SourceFormat),
        enum_check("validation_status", ValidationStatus),
        CheckConstraint("graph_hash ~ '^sha256:[0-9a-f]{64}$'", name="graph_hash_format"),
        # Compilation is deterministic, so identical source yields an
        # identical hash; indexed so the compiler can skip a rebuild.
        Index("ix_pipeline_revisions_graph_hash", "graph_hash"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    pipeline_id: Mapped[uuid.UUID] = uuid_fk("pipelines.id", index=True)
    version: Mapped[int] = mapped_column(nullable=False)
    source_format: Mapped[str] = status_column(SourceFormat, SourceFormat.YAML)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    ir_version: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text(f"'{IR_VERSION}'")
    )
    compiled_spec: Mapped[dict[str, Any]] = jsonb()
    input_schema: Mapped[dict[str, Any]] = jsonb()
    output_schema: Mapped[dict[str, Any]] = jsonb()
    # "sha256:" plus 64 hex characters. The prefix is carried so the digest
    # algorithm is never implicit, which means 71 characters, not 64.
    graph_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    validation_status: Mapped[str] = status_column(ValidationStatus, ValidationStatus.PENDING)
    validation_report: Mapped[dict[str, Any]] = jsonb()
    # Null means "the environment default at run time"; a value pins this
    # revision to one environment.
    runtime_environment_id: Mapped[uuid.UUID | None] = uuid_fk(
        "runtime_environments.id", nullable=True
    )
    created_by: Mapped[uuid.UUID] = uuid_fk("users.id")
    created_at: Mapped[datetime] = created_at()


class PipelineInput(Base):
    """A public input, normalised out of the compiled spec for querying.

    These are the values the current system marks ``$WILL_PROVIDE$``: what a
    researcher must supply before the pipeline can run.
    """

    __tablename__ = "pipeline_inputs"
    __table_args__ = (
        UniqueConstraint(
            "pipeline_revision_id", "key", name="uq_pipeline_inputs_pipeline_revision_id_key"
        ),
        enum_check("primitive_type", PrimitiveType),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    pipeline_revision_id: Mapped[uuid.UUID] = uuid_fk(
        "pipeline_revisions.id", ondelete="CASCADE", index=True
    )
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    type_ref: Mapped[str | None] = mapped_column(String(128))
    primitive_type: Mapped[str] = status_column(PrimitiveType)
    required: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    default_value: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    constraints: Mapped[dict[str, Any]] = jsonb()
    source_policy: Mapped[dict[str, Any]] = jsonb()


class PipelineOutput(Base):
    __tablename__ = "pipeline_outputs"
    __table_args__ = (
        UniqueConstraint(
            "pipeline_revision_id", "key", name="uq_pipeline_outputs_pipeline_revision_id_key"
        ),
        enum_check("artifact_kind", ArtifactKind),
        enum_check("visibility", Visibility),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    pipeline_revision_id: Mapped[uuid.UUID] = uuid_fk(
        "pipeline_revisions.id", ondelete="CASCADE", index=True
    )
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    artifact_kind: Mapped[str] = status_column(ArtifactKind, ArtifactKind.TASK_OUTPUT)
    visibility: Mapped[str] = status_column(Visibility, Visibility.PRIVATE)
    delivery_modes: Mapped[dict[str, Any]] = jsonb(default="'[]'::jsonb")
    retention_policy: Mapped[dict[str, Any]] = jsonb()
