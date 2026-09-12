"""Authoring use cases: create a pipeline, compile a revision.

A revision is immutable once written — enforced by a database trigger, not by
convention — so everything that must be true about it has to be true before the
insert. Compilation therefore happens first, and a document with errors never
reaches the database.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.domain.compiler import LibraryLoader, compile_pipeline
from app.domain.errors import DomainError, ValidationFailed
from app.domain.ir import CompilationResult, Diagnostic
from app.infrastructure.db.models import (
    Pipeline,
    PipelineInput,
    PipelineOutput,
    PipelineRevision,
    Project,
)
from app.infrastructure.pipeline_loader import parse_document


class CompilationFailed(DomainError):
    """A document that cannot compile never becomes a revision."""

    code = "pipeline.compilation_failed"

    def __init__(self, diagnostics: list[Diagnostic]) -> None:
        errors = [d for d in diagnostics if d.severity == "error"]
        super().__init__(
            f"Pipeline failed to compile with {len(errors)} error(s).",
            details={"errors": [d.model_dump(mode="json") for d in errors]},
        )
        self.diagnostics = diagnostics


@dataclass(frozen=True, slots=True)
class RevisionCreated:
    revision_id: uuid.UUID
    pipeline_id: uuid.UUID
    version: int
    graph_hash: str
    reused: bool
    """True when an identical document already had a revision.

    Compilation is deterministic and revisions are immutable, so recompiling
    unchanged source is the same artefact. Returning it avoids a stream of
    identical versions from a save button.
    """
    warnings: list[Diagnostic]


def default_project_id(session: Session) -> uuid.UUID:
    """The single seeded project.

    Tenancy columns exist but nothing scopes by them yet (ADR 0009), so every
    service resolves the one default project rather than inventing a parameter
    callers cannot answer.
    """
    project_id = session.execute(select(Project.id).where(Project.is_default)).scalar_one_or_none()
    if project_id is None:
        raise ValidationFailed(
            "No default project exists. The base migration seeds one; the "
            "database may not be migrated to head."
        )
    return project_id


def get_or_create_pipeline(
    session: Session, *, slug: str, title: str, owner_id: uuid.UUID
) -> Pipeline:
    """Find a pipeline by slug, or create it."""
    project_id = default_project_id(session)
    pipeline = session.execute(
        select(Pipeline).where(Pipeline.project_id == project_id, Pipeline.slug == slug)
    ).scalar_one_or_none()
    if pipeline is not None:
        return pipeline
    pipeline = Pipeline(project_id=project_id, slug=slug, title=title, owner_id=owner_id)
    session.add(pipeline)
    session.flush()
    return pipeline


def create_revision(
    session: Session,
    *,
    source_text: str,
    owner_id: uuid.UUID,
    load_library: LibraryLoader | None = None,
    title: str | None = None,
) -> RevisionCreated:
    """Compile a document and store it as an immutable revision.

    Raises :class:`CompilationFailed` before touching the database if the
    document has errors, so a broken pipeline cannot be published.
    """
    document = parse_document(source_text)
    result: CompilationResult = compile_pipeline(document, load_library=load_library)
    if not result.ok:
        raise CompilationFailed(result.diagnostics)
    compiled = result.pipeline
    assert compiled is not None  # guarded by result.ok

    pipeline = get_or_create_pipeline(
        session,
        slug=document.pipeline.replace("_", "-").lower(),
        title=title or document.title or document.pipeline,
        owner_id=owner_id,
    )

    # Lock the parent so two concurrent submissions cannot allocate the same
    # version number. Locking the parent rather than the revisions works even
    # when there are no revisions yet.
    session.execute(text("SELECT id FROM pipelines WHERE id = :id FOR UPDATE"), {"id": pipeline.id})

    latest = session.execute(
        select(PipelineRevision)
        .where(PipelineRevision.pipeline_id == pipeline.id)
        .order_by(PipelineRevision.version.desc())
        .limit(1)
    ).scalar_one_or_none()

    if (
        latest is not None
        and latest.graph_hash == compiled.graph_hash
        and latest.source_text == source_text
    ):
        return RevisionCreated(
            revision_id=latest.id,
            pipeline_id=pipeline.id,
            version=latest.version,
            graph_hash=latest.graph_hash,
            reused=True,
            warnings=result.warnings,
        )

    revision = PipelineRevision(
        pipeline_id=pipeline.id,
        version=(latest.version + 1) if latest else 1,
        source_text=source_text,
        ir_version=compiled.ir_version,
        compiled_spec=compiled.model_dump(mode="json"),
        input_schema={"inputs": [i.model_dump(mode="json") for i in compiled.inputs]},
        output_schema={
            "outputs": [
                {"stage": stage.key, **output.model_dump(mode="json")}
                for stage in compiled.stages
                for output in stage.outputs
            ]
        },
        graph_hash=compiled.graph_hash,
        validation_status="valid",
        validation_report={"diagnostics": [d.model_dump(mode="json") for d in result.diagnostics]},
        created_by=owner_id,
    )
    session.add(revision)
    session.flush()

    # Normalised copies, for querying. The compiled spec stays authoritative.
    for declared in compiled.inputs:
        session.add(
            PipelineInput(
                pipeline_revision_id=revision.id,
                key=declared.key,
                type_ref=declared.type_ref,
                primitive_type=_primitive_for(declared.accept),
                required=declared.required,
                source_policy={"sources": [s.value for s in declared.sources]},
            )
        )
    seen_outputs: set[str] = set()
    for stage in compiled.stages:
        for output in stage.outputs:
            # Output keys repeat across matrix rows; the public surface is the
            # set of names, not one row's copy of them.
            if output.key in seen_outputs:
                continue
            seen_outputs.add(output.key)
            session.add(
                PipelineOutput(
                    pipeline_revision_id=revision.id,
                    key=output.key,
                    delivery_modes=[mode.value for mode in output.delivery],
                    retention_policy=(
                        {"days": output.retention_days} if output.retention_days else {}
                    ),
                )
            )
    session.flush()

    return RevisionCreated(
        revision_id=revision.id,
        pipeline_id=pipeline.id,
        version=revision.version,
        graph_hash=revision.graph_hash,
        reused=False,
        warnings=result.warnings,
    )


def _primitive_for(accept: str) -> str:
    return {"file": "file", "directory": "directory"}.get(accept, "string")


def load_compiled(session: Session, revision_id: uuid.UUID):
    """Read a revision's IR back.

    A run reads this; it never recompiles, so a later release can decide
    whether it is able to execute an older ``ir_version``.
    """
    from app.domain.ir import CompiledPipeline

    revision = session.get(PipelineRevision, revision_id)
    if revision is None:
        raise ValidationFailed(f"Pipeline revision {revision_id} does not exist.")
    return CompiledPipeline.model_validate(revision.compiled_spec)
