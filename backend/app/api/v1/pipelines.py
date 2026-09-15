"""Pipeline authoring: revisions, listing, and compile preview."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import AdminUser, Db
from app.api.schemas import (
    CompiledInputResponse,
    CompiledStageResponse,
    CompilePreviewRequest,
    CompilePreviewResponse,
    CreateRevisionRequest,
    DiagnosticResponse,
    Page,
    PipelineSummary,
    RevisionResponse,
)
from app.application.pipelines import CompilationFailed, create_revision
from app.domain.compiler import compile_pipeline
from app.domain.enums import TaskClass
from app.domain.errors import ValidationFailed
from app.infrastructure.db.models import Pipeline, PipelineRevision
from app.infrastructure.pipeline_loader import parse_document

router = APIRouter(prefix="/pipelines", tags=["pipelines"])


def _structural(error: ValidationFailed) -> list[DiagnosticResponse]:
    """A parse or schema failure, as diagnostics the editor already renders."""
    raw = error.details.get("errors")
    problems = [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []
    if not problems:
        return [DiagnosticResponse(severity="error", code=error.code, message=error.message)]
    return [
        DiagnosticResponse(
            severity="error",
            code=error.code,
            message=str(problem.get("message", "")),
            location=str(problem.get("path", "")),
        )
        for problem in problems
    ]


def _diagnostics(items) -> list[DiagnosticResponse]:
    return [
        DiagnosticResponse(
            severity=item.severity,
            code=item.code,
            message=item.message,
            location=item.location,
        )
        for item in items
    ]


@router.get("", response_model=Page[PipelineSummary])
def list_pipelines(
    db: Db, _admin: AdminUser, limit: int = 50, cursor: str | None = None
) -> Page[PipelineSummary]:
    """List pipelines, newest first.

    Cursor-based: a collection that grows without bound should not be paged by
    offset, because a row inserted mid-scan shifts every later page.
    """
    query = select(Pipeline).order_by(Pipeline.created_at.desc(), Pipeline.id.desc())
    if cursor:
        try:
            anchor = uuid.UUID(cursor)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "request.invalid", "message": "Malformed cursor."},
            ) from None
        marker = db.get(Pipeline, anchor)
        if marker is not None:
            query = query.where(Pipeline.created_at < marker.created_at)
    rows = list(db.execute(query.limit(min(limit, 200) + 1)).scalars())
    has_more = len(rows) > min(limit, 200)
    rows = rows[: min(limit, 200)]
    return Page[PipelineSummary](
        items=[PipelineSummary.model_validate(row) for row in rows],
        next_cursor=str(rows[-1].id) if has_more and rows else None,
    )


@router.post("/revisions", response_model=RevisionResponse, status_code=status.HTTP_201_CREATED)
def create_pipeline_revision(
    payload: CreateRevisionRequest, db: Db, admin: AdminUser
) -> RevisionResponse:
    """Compile a document and store it as an immutable revision.

    A document with errors never reaches the database, so a broken pipeline
    cannot be published and then discovered at run time.
    """
    try:
        created = create_revision(
            db,
            source_text=payload.source_text,
            owner_id=admin.user_id,
            title=payload.title,
        )
    except CompilationFailed as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": error.code,
                "message": error.message,
                "details": error.details,
            },
        ) from error
    return RevisionResponse(
        revision_id=created.revision_id,
        pipeline_id=created.pipeline_id,
        version=created.version,
        graph_hash=created.graph_hash,
        reused=created.reused,
        warnings=_diagnostics(created.warnings),
    )


@router.post("/compile-preview", response_model=CompilePreviewResponse)
def compile_preview(
    payload: CompilePreviewRequest, db: Db, _admin: AdminUser
) -> CompilePreviewResponse:
    """Compile without storing anything.

    Returns diagnostics, the public input contract, and the resulting stage
    graph, so an author can see what a document will do before committing to a
    revision they cannot edit afterwards.

    A document that is structurally wrong comes back the same way one that is
    semantically wrong does: as diagnostics, with a 200. Which layer objected
    -- the schema or the compiler -- is our business, not the author's, and
    splitting it across two response shapes only makes a client handle the
    same situation twice.
    """
    try:
        document = parse_document(payload.source_text)
    except ValidationFailed as error:
        return CompilePreviewResponse(ok=False, diagnostics=_structural(error))
    result = compile_pipeline(document, provided=payload.values)
    if not result.ok:
        return CompilePreviewResponse(ok=False, diagnostics=_diagnostics(result.diagnostics))
    compiled = result.pipeline
    assert compiled is not None
    return CompilePreviewResponse(
        ok=True,
        graph_hash=compiled.graph_hash,
        inputs=[
            CompiledInputResponse.model_validate(declared, from_attributes=True)
            for declared in compiled.inputs
        ],
        stages=[
            CompiledStageResponse(
                key=stage.key,
                name=stage.name,
                variant=stage.variant,
                needs=stage.needs,
                fanout=stage.fanout.type,
                steps=[step.name for step in stage.steps],
                outputs=[output.key for output in stage.outputs],
                task_class=TaskClass(stage.task_class),
            )
            for stage in compiled.stages
        ],
        diagnostics=_diagnostics(result.diagnostics),
    )


@router.get("/{pipeline_id}/revisions", response_model=Page[RevisionResponse])
def list_revisions(
    pipeline_id: uuid.UUID, db: Db, _admin: AdminUser, limit: int = 50
) -> Page[RevisionResponse]:
    rows = list(
        db.execute(
            select(PipelineRevision)
            .where(PipelineRevision.pipeline_id == pipeline_id)
            .order_by(PipelineRevision.version.desc())
            .limit(min(limit, 200))
        ).scalars()
    )
    return Page[RevisionResponse](
        items=[
            RevisionResponse(
                revision_id=row.id,
                pipeline_id=row.pipeline_id,
                version=row.version,
                graph_hash=row.graph_hash,
                reused=False,
            )
            for row in rows
        ]
    )
