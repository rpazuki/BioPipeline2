"""The catalog: what a researcher browses and submits against.

Open to any signed-in user, and it shows only published entries. What it does
*not* show is as deliberate as what it does: no bindings, no pipeline revision
ids, no draft revisions, no hidden or fixed fields. A researcher submits
against a contract, and the wiring behind it is not part of that contract.
"""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Response, status

from app.api.deps import CurrentUser, Db
from app.api.schemas import (
    CatalogDetail,
    CatalogSubmitRequest,
    CatalogSummary,
    DiagnosticResponse,
    Page,
    PublicationFieldResponse,
    SubmitRunResponse,
)
from app.application.publications import (
    CatalogEntry,
    SubmissionRefused,
    bind_submission,
    catalog,
    catalog_entry,
)
from app.application.runs import SubmissionRejected, submit_run
from app.domain.enums import FieldVisibility, PrimitiveType, RunTrigger
from app.infrastructure.fanout import DirectoryFanOut
from app.infrastructure.mounts import readable_roots

router = APIRouter(prefix="/catalog", tags=["catalog"])


def _visible_fields(entry: CatalogEntry) -> list[PublicationFieldResponse]:
    """Only what the form should render.

    A hidden or fixed field is applied server-side at submission. Sending it
    here would both clutter the form and publish a value the admin chose not to
    expose.
    """
    return [
        PublicationFieldResponse(
            key=field.key,
            label=field.label,
            field_type=PrimitiveType(field.field_type),
            required=field.required,
            help_text=field.help_text,
            placeholder=field.placeholder,
            ui_group=field.ui_group,
            default_value=field.default_value,
            type_ref=field.type_ref,
            source_policy=field.source_policy,
            order_index=field.order_index,
        )
        for field in entry.fields
        if field.visibility != FieldVisibility.HIDDEN
    ]


@router.get("", response_model=Page[CatalogSummary])
def list_catalog(
    db: Db, _user: CurrentUser, search: str | None = None, limit: int = 50
) -> Page[CatalogSummary]:
    entries = catalog(db, search=search, limit=limit)
    return Page[CatalogSummary](
        items=[
            CatalogSummary(
                slug=entry.slug,
                title=entry.title,
                description=entry.description,
                version=entry.version,
            )
            for entry in entries
        ],
        total=len(entries),
    )


def _entry_or_404(db: Db, slug: str) -> CatalogEntry:
    entry = catalog_entry(db, slug=slug)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "catalog.not_found", "message": "No such catalog entry."},
        )
    return entry


@router.get("/{slug}", response_model=CatalogDetail)
def read_catalog_entry(slug: str, db: Db, _user: CurrentUser) -> CatalogDetail:
    entry = _entry_or_404(db, slug)
    return CatalogDetail(
        slug=entry.slug,
        title=entry.title,
        description=entry.description,
        version=entry.version,
        publication_id=entry.publication_id,
        revision_id=entry.revision_id,
        fields=_visible_fields(entry),
    )


@router.post("/{slug}/runs", response_model=SubmitRunResponse, status_code=status.HTTP_201_CREATED)
def submit_from_catalog(
    slug: str,
    payload: CatalogSubmitRequest,
    db: Db,
    principal: CurrentUser,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> SubmitRunResponse:
    """Start a run from a catalog entry.

    The submitted values are the publication's field keys; the bindings turn
    them into a plan against the pipeline revision this entry pins. Nothing
    patches the revision, which is immutable and may be shared with other
    entries (ADR 0031).

    The run records what the researcher filled in, not the translation, so that
    six months later the run is still readable by the person who submitted it.
    """
    entry = _entry_or_404(db, slug)
    try:
        plan = bind_submission(db, entry=entry, submitted=payload.values)
    except SubmissionRefused as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": error.code, "message": error.message, "details": error.details},
        ) from error

    try:
        submitted = submit_run(
            db,
            pipeline_revision_id=entry.pipeline_revision_id,
            publication_revision_id=entry.revision_id,
            requested_by=principal.user_id,
            values=plan.values,
            recorded_values=plan.submitted,
            compiled=plan.pipeline,
            idempotency_key=idempotency_key,
            trigger=RunTrigger.API,
            enumerate_fanout=DirectoryFanOut(readable_roots(db)),
        )
    except SubmissionRejected as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": error.code, "message": error.message, "details": error.details},
        ) from error

    if submitted.reused:
        response.status_code = status.HTTP_200_OK
    return SubmitRunResponse(
        run_id=submitted.run_id,
        task_count=submitted.task_count,
        reused=submitted.reused,
        warnings=[
            DiagnosticResponse(
                severity=d.severity, code=d.code, message=d.message, location=d.location
            )
            for d in submitted.warnings
        ],
    )
