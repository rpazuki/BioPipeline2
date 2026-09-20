"""Publications: authoring and releasing a catalog entry.

Admin-only, and separate from the catalog routes on purpose. What an admin
sees — bindings, pipeline revision ids, draft revisions — is deliberately not
what a researcher sees, and keeping the two in one router makes it easy to leak
the first into the second by adding a field.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import AdminUser, Audit, Db
from app.api.schemas import (
    CreatePublicationRevisionRequest,
    DiagnosticResponse,
    Page,
    PublicationRevisionResponse,
    PublicationSummary,
)
from app.application import audit as audit_log
from app.application.publications import (
    FieldSpec,
    PublishRejected,
    archive,
    create_publication_revision,
    publish,
)
from app.domain.bindings import FieldBinding
from app.domain.enums import PublicationStatus
from app.infrastructure.db.models import Publication

router = APIRouter(prefix="/publications", tags=["publications"])


@router.get("", response_model=Page[PublicationSummary])
def list_publications(
    db: Db, _admin: AdminUser, limit: int = 50, status_filter: str | None = None
) -> Page[PublicationSummary]:
    query = select(Publication).order_by(Publication.created_at.desc())
    if status_filter:
        query = query.where(Publication.status == status_filter)
    rows = list(db.execute(query.limit(min(limit, 200))).scalars())
    return Page[PublicationSummary](
        items=[PublicationSummary.model_validate(row) for row in rows], total=len(rows)
    )


@router.post(
    "/revisions",
    response_model=PublicationRevisionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_revision(
    payload: CreatePublicationRevisionRequest, db: Db, admin: AdminUser
) -> PublicationRevisionResponse:
    """Validate a publication against its pipeline, then store it.

    Every binding is checked against the pipeline revision's compiled IR first.
    A field wired to a stage, step or parameter that does not exist fails here
    rather than becoming a control that silently drops what people type into
    it (ADR 0031).
    """
    try:
        created = create_publication_revision(
            db,
            slug=payload.slug,
            pipeline_revision_id=payload.pipeline_revision_id,
            title=payload.title,
            description=payload.description,
            display_metadata=payload.display_metadata,
            created_by=admin.user_id,
            fields=[
                FieldSpec(
                    key=field.key,
                    label=field.label,
                    binding=FieldBinding(
                        key=field.key,
                        target=field.binding.target,
                        stage=field.binding.stage,
                        step=field.binding.step,
                        binding_key=field.binding.binding_key,
                    ),
                    field_type=field.field_type,
                    required=field.required,
                    help_text=field.help_text,
                    placeholder=field.placeholder,
                    order_index=index,
                    ui_group=field.ui_group,
                    default_value=field.default_value,
                    fixed_value=field.fixed_value,
                    visibility=field.visibility,
                    type_ref=field.type_ref,
                    saveable=field.saveable,
                    source_policy=field.source_policy,
                    delivery_policy=field.delivery_policy,
                )
                for index, field in enumerate(payload.fields)
            ],
        )
    except PublishRejected as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": error.code, "message": error.message, "details": error.details},
        ) from error

    return PublicationRevisionResponse(
        publication_id=created.publication_id,
        revision_id=created.revision_id,
        version=created.version,
        warnings=[
            DiagnosticResponse(
                severity=d.severity, code=d.code, message=d.message, location=d.location
            )
            for d in created.warnings
        ],
    )


def _publication_or_404(db: Db, publication_id: uuid.UUID) -> Publication:
    publication = db.get(Publication, publication_id)
    if publication is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "publication.not_found", "message": "No such publication."},
        )
    return publication


@router.post("/{publication_id}/publish", response_model=PublicationSummary)
def publish_revision(
    publication_id: uuid.UUID, revision_id: uuid.UUID, db: Db, _admin: AdminUser, context: Audit
) -> PublicationSummary:
    """Open one revision to the catalog.

    Separate from creating it, so an admin can prepare a revision, look at the
    form it produces, and only then make it the one researchers see.
    """
    publication = _publication_or_404(db, publication_id)
    publish(db, publication_id=publication_id, revision_id=revision_id)
    # What a researcher submits against changed. Six months later, "which
    # revision was live in March" is the question, and this is the answer.
    audit_log.record(
        db,
        action=audit_log.CATALOG_PUBLISHED,
        target_type="publication",
        target_id=publication_id,
        context=context,
        slug=publication.slug,
        revision_id=str(revision_id),
    )
    db.refresh(publication)
    return PublicationSummary.model_validate(publication)


@router.post("/{publication_id}/archive", response_model=PublicationSummary)
def archive_publication(
    publication_id: uuid.UUID, db: Db, _admin: AdminUser, context: Audit
) -> PublicationSummary:
    """Withdraw an entry.

    The revision and the runs that point at it stay: this removes an entry from
    the list of things to start, not from the record of what happened.
    """
    publication = _publication_or_404(db, publication_id)
    if publication.status == PublicationStatus.ARCHIVED:
        return PublicationSummary.model_validate(publication)
    archive(db, publication_id=publication_id)
    audit_log.record(
        db,
        action=audit_log.CATALOG_ARCHIVED,
        target_type="publication",
        target_id=publication_id,
        context=context,
        slug=publication.slug,
    )
    db.refresh(publication)
    return PublicationSummary.model_validate(publication)
