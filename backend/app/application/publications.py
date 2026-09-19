"""Publications: the curated contract a researcher actually submits against.

A pipeline revision says what a pipeline *can* take. A publication says what
this particular offering asks for, in the words a researcher uses, with the
fields an admin chose to expose and the rest fixed or hidden. The two are
separate because they change for different reasons: re-authoring a pipeline
should not silently change a catalog entry, and relabelling a field should not
require recompiling a pipeline.

Publishing is treated like releasing a version. A publication revision is
immutable, it pins exactly one pipeline revision, and every binding in it is
validated against that revision's compiled IR before it is stored — so a form
control wired to nothing fails the publish rather than being discovered by a
researcher whose values were silently ignored.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.application.pipelines import default_project_id, load_compiled
from app.domain import types
from app.domain.bindings import (
    FieldBinding,
    apply_bindings,
    infer_type_schemas,
    infer_value_types,
    validate_bindings,
)
from app.domain.enums import BindingTarget, FieldVisibility, PublicationStatus
from app.domain.errors import ValidationFailed
from app.domain.ir import Diagnostic
from app.infrastructure.db.models import (
    Publication,
    PublicationField,
    PublicationRevision,
)


class PublishRejected(ValidationFailed):
    """A publication whose bindings do not fit its pipeline is never stored."""

    code = "publication.invalid"

    def __init__(self, diagnostics: list[Diagnostic]) -> None:
        errors = [d for d in diagnostics if d.severity == "error"]
        super().__init__(
            f"The publication could not be created: {len(errors)} error(s).",
            details={"errors": [d.model_dump(mode="json") for d in errors]},
        )
        self.diagnostics = diagnostics


class SubmissionRefused(ValidationFailed):
    """The submitted values do not satisfy the published contract.

    A ``ValidationFailed`` so that every route answers it the same way. The
    request was understood perfectly well; the values in it cannot produce a
    run, which is 422 rather than 400 — and a schedule refused at creation
    must say the same thing as a submission refused at the catalog.
    """

    code = "catalog.values_invalid"

    def __init__(self, problems: list[dict[str, str]]) -> None:
        super().__init__(
            "The submitted values do not satisfy this catalog entry.",
            details={"errors": problems},
        )


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """One field as an admin defines it, before it is stored."""

    key: str
    label: str
    binding: FieldBinding
    field_type: str = "string"
    required: bool = True
    help_text: str | None = None
    placeholder: str | None = None
    order_index: int = 0
    ui_group: str | None = None
    default_value: Any = None
    fixed_value: Any = None
    visibility: str = FieldVisibility.VISIBLE
    type_ref: str | None = None
    # Whether a researcher may keep what they filled in and use it again.
    # `None` means "if it is typed", which is what saving is for: a
    # five-key rule object is worth keeping, a thread count is not.
    saveable: bool | None = None
    source_policy: dict[str, Any] | None = None
    delivery_policy: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class PublicationRevisionCreated:
    publication_id: uuid.UUID
    revision_id: uuid.UUID
    version: int
    warnings: list[Diagnostic]


def get_or_create_publication(session: Session, *, slug: str, created_by: uuid.UUID) -> Publication:
    project_id = default_project_id(session)
    existing = session.execute(
        select(Publication).where(Publication.project_id == project_id, Publication.slug == slug)
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    publication = Publication(project_id=project_id, slug=slug, created_by=created_by)
    session.add(publication)
    session.flush()
    return publication


def create_publication_revision(
    session: Session,
    *,
    slug: str,
    pipeline_revision_id: uuid.UUID,
    title: str,
    fields: list[FieldSpec],
    created_by: uuid.UUID,
    description: str | None = None,
    display_metadata: dict[str, Any] | None = None,
) -> PublicationRevisionCreated:
    """Validate a publication against its pipeline, then store it.

    Nothing reaches the database until every binding resolves, because a
    publication revision is immutable: a broken one could not be corrected,
    only superseded, and in the meantime it is a catalog entry that quietly
    drops what people type into it.
    """
    compiled = load_compiled(session, pipeline_revision_id)
    if compiled is None:
        raise ValidationFailed(
            f"Pipeline revision {pipeline_revision_id} does not exist.",
            details={"pipeline_revision_id": str(pipeline_revision_id)},
        )

    bindings = [spec.binding for spec in fields]
    diagnostics = validate_bindings(compiled, bindings)
    diagnostics.extend(_validate_fields(fields))
    diagnostics.extend(_validate_inputs_are_covered(compiled, fields))
    if any(item.severity == "error" for item in diagnostics):
        raise PublishRejected(diagnostics)

    publication = get_or_create_publication(session, slug=slug, created_by=created_by)

    # Lock the parent so two concurrent publishes cannot take the same version
    # number. Locking the parent works even when there are no revisions yet.
    session.execute(
        text("SELECT id FROM publications WHERE id = :id FOR UPDATE"), {"id": publication.id}
    )
    latest = session.execute(
        select(PublicationRevision.version)
        .where(PublicationRevision.publication_id == publication.id)
        .order_by(PublicationRevision.version.desc())
        .limit(1)
    ).scalar_one_or_none()

    revision = PublicationRevision(
        publication_id=publication.id,
        pipeline_revision_id=pipeline_revision_id,
        version=(latest or 0) + 1,
        title=title,
        description=description,
        display_metadata=display_metadata or {},
        access_policy={},
        created_by=created_by,
    )
    session.add(revision)
    session.flush()

    types = infer_value_types(compiled, bindings)
    schemas = infer_type_schemas(compiled, bindings)
    for index, spec in enumerate(fields):
        session.add(
            PublicationField(
                publication_revision_id=revision.id,
                binding_target=spec.binding.target,
                binding_stage=spec.binding.stage,
                binding_step=spec.binding.step,
                binding_key=spec.binding.binding_key,
                binding_value_type=types.get(spec.key),
                key=spec.key,
                label=spec.label,
                help_text=spec.help_text,
                placeholder=spec.placeholder,
                field_type=spec.field_type,
                type_ref=spec.type_ref,
                type_schema=schemas.get(spec.key),
                required=spec.required,
                order_index=spec.order_index or index,
                ui_group=spec.ui_group,
                default_value=spec.default_value,
                fixed_value=spec.fixed_value,
                constraints={},
                source_policy=spec.source_policy or {},
                delivery_policy=spec.delivery_policy or {},
                save_policy={
                    "saveable": (
                        spec.saveable
                        if spec.saveable is not None
                        else schemas.get(spec.key) is not None
                    )
                },
                visibility=spec.visibility,
            )
        )
    session.flush()

    return PublicationRevisionCreated(
        publication_id=publication.id,
        revision_id=revision.id,
        version=revision.version,
        warnings=[item for item in diagnostics if item.severity == "warning"],
    )


# Types a form cannot coerce, because the value is a path or a reference
# rather than a number: they are validated where they are resolved.
_UNCOERCED = frozenset({"file", "directory", "url", "object", "array"})


def _coerce_submitted(
    by_key: dict[str, Any], effective: dict[str, Any], problems: list[dict[str, str]]
) -> dict[str, Any]:
    """Turn what the form sent into what the pipeline's types say it is (G93).

    Every value in an HTML submission is a string. The real system never
    coerced them, so `"200"` reached a science function against a type
    declaring integer, and what happened next depended on how tolerant that
    function happened to be. The frozen `type_schema` is what makes this
    possible at all — the definition it came from may have changed since, and
    what this entry asked for on the day it was published is what it still
    asks for.

    Problems are reported per field, and all of them at once: a form that
    reports one error per submission is a form somebody fills in six times.
    """
    coerced = dict(effective)
    for key, value in effective.items():
        field = by_key.get(key)
        if field is None:
            continue
        if field.type_schema:
            try:
                coerced[key] = types.coerce(value, field.type_schema, path=key)
            except types.ValueRejected as rejected:
                problems.extend(
                    {"path": f"values.{item['path']}", "message": item["message"]}
                    for item in rejected.problems
                )
            continue
        if field.field_type in _UNCOERCED:
            continue
        if field.field_type == "enum":
            # The options live in `constraints` when an admin narrowed them;
            # with none, anything the pipeline accepts is allowed through.
            continue
        try:
            coerced[key] = types.coerce_scalar(value, field.field_type, key)
        except Exception as error:
            problems.append({"path": f"values.{key}", "message": str(error)})
    return coerced


def _validate_inputs_are_covered(compiled, fields: list[FieldSpec]) -> list[Diagnostic]:
    """Every value the pipeline asks for must have somewhere to come from.

    A public input is one the author marked `$WILL_PROVIDE$`, so it has no
    default and materialisation refuses without it. A publication that neither
    exposes it nor fixes it is therefore one that can never produce a run — and
    the person who finds out is a researcher who filled in a form and got an
    error about a field they never saw.
    """
    bound = {
        spec.binding.binding_key
        for spec in fields
        if spec.binding.target == BindingTarget.DEFAULT_VALUE
    }
    missing = [declared.key for declared in compiled.inputs if declared.key not in bound]
    if not missing:
        return []
    return [
        Diagnostic(
            severity="error",
            code="publication.input_not_covered",
            message=(
                f"The pipeline asks for '{key}' and no field supplies it, so no submission "
                "could ever run. Add a field bound to it, or fix its value."
            ),
            location=key,
        )
        for key in missing
    ]


def _validate_fields(fields: list[FieldSpec]) -> list[Diagnostic]:
    """Rules about the field itself rather than about where it points."""
    diagnostics: list[Diagnostic] = []
    for spec in fields:
        if spec.fixed_value is not None and spec.visibility != FieldVisibility.HIDDEN:
            # The database refuses this too; saying so here names the field
            # rather than surfacing a constraint name.
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="publication.fixed_value_is_visible",
                    message=(
                        f"Field '{spec.key}' has a fixed value but is visible. A value a "
                        "researcher can edit is not fixed; hide it or drop the fixed value."
                    ),
                    location=spec.key,
                )
            )
        if spec.required and spec.fixed_value is None and spec.visibility == FieldVisibility.HIDDEN:
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="publication.required_field_is_hidden",
                    message=(
                        f"Field '{spec.key}' is required and hidden, with nothing to supply "
                        "it, so no submission could ever satisfy it."
                    ),
                    location=spec.key,
                )
            )
    return diagnostics


def publish(session: Session, *, publication_id: uuid.UUID, revision_id: uuid.UUID) -> None:
    """Point a publication at one of its revisions and open it to the catalog."""
    revision = session.get(PublicationRevision, revision_id)
    if revision is None or revision.publication_id != publication_id:
        raise ValidationFailed("That revision does not belong to this publication.")
    publication = session.get(Publication, publication_id)
    if publication is None:
        raise ValidationFailed("No such publication.")
    publication.current_revision_id = revision_id
    publication.status = PublicationStatus.PUBLISHED
    session.flush()


def archive(session: Session, *, publication_id: uuid.UUID) -> None:
    """Withdraw an entry from the catalog.

    The revision stays, and so do the runs that point at it: archiving removes
    an entry from the list of things to start, not from the record of what
    happened.
    """
    publication = session.get(Publication, publication_id)
    if publication is None:
        raise ValidationFailed("No such publication.")
    publication.status = PublicationStatus.ARCHIVED
    session.flush()


# --- the catalog -----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    publication_id: uuid.UUID
    slug: str
    revision_id: uuid.UUID
    version: int
    title: str
    description: str | None
    pipeline_revision_id: uuid.UUID
    fields: list[PublicationField]


def catalog(session: Session, *, search: str | None = None, limit: int = 50) -> list[CatalogEntry]:
    """Published entries, newest first.

    Only `published`: a draft is an admin's work in progress and an archived
    entry is one somebody deliberately withdrew.
    """
    query = (
        select(Publication, PublicationRevision)
        .join(PublicationRevision, Publication.current_revision_id == PublicationRevision.id)
        .where(Publication.status == PublicationStatus.PUBLISHED)
        .order_by(PublicationRevision.created_at.desc())
        .limit(min(limit, 200))
    )
    if search:
        pattern = f"%{search}%"
        query = query.where(
            PublicationRevision.title.ilike(pattern)
            | PublicationRevision.description.ilike(pattern)
        )
    return [
        _entry(session, publication, revision, with_fields=False)
        for publication, revision in session.execute(query)
    ]


def catalog_entry(session: Session, *, slug: str) -> CatalogEntry | None:
    row = session.execute(
        select(Publication, PublicationRevision)
        .join(PublicationRevision, Publication.current_revision_id == PublicationRevision.id)
        .where(
            Publication.slug == slug,
            Publication.status == PublicationStatus.PUBLISHED,
        )
    ).one_or_none()
    if row is None:
        return None
    publication, revision = row
    return _entry(session, publication, revision, with_fields=True)


def entry_for_revision(
    session: Session, *, revision_id: uuid.UUID, published_only: bool = True
) -> CatalogEntry | None:
    """One entry by the *revision* it pins, rather than by its slug.

    A schedule points at a revision, not at a publication, so re-publishing a
    catalog entry never silently changes what a schedule has been running. The
    publication is still consulted for its status: archiving an entry removes
    it from the things that can be started, and a clock is one of the things
    that starts them.
    """
    row = session.execute(
        select(Publication, PublicationRevision)
        .join(PublicationRevision, PublicationRevision.publication_id == Publication.id)
        .where(PublicationRevision.id == revision_id)
    ).one_or_none()
    if row is None:
        return None
    publication, revision = row
    if published_only and publication.status != PublicationStatus.PUBLISHED:
        return None
    return _entry(session, publication, revision, with_fields=True)


def _entry(
    session: Session,
    publication: Publication,
    revision: PublicationRevision,
    *,
    with_fields: bool,
) -> CatalogEntry:
    fields: list[PublicationField] = []
    if with_fields:
        fields = list(
            session.execute(
                select(PublicationField)
                .where(PublicationField.publication_revision_id == revision.id)
                .order_by(PublicationField.order_index, PublicationField.key)
            ).scalars()
        )
    return CatalogEntry(
        publication_id=publication.id,
        slug=publication.slug,
        revision_id=revision.id,
        version=revision.version,
        title=revision.title,
        description=revision.description,
        pipeline_revision_id=revision.pipeline_revision_id,
        fields=fields,
    )


@dataclass(frozen=True, slots=True)
class BoundPlan:
    """A catalog submission, translated into something materialisable."""

    entry: CatalogEntry
    pipeline: Any
    values: dict[str, Any]
    submitted: dict[str, Any]


def bind_submission(
    session: Session, *, entry: CatalogEntry, submitted: dict[str, Any]
) -> BoundPlan:
    """Turn what a researcher filled in into a plan, or say why it cannot be.

    Hidden fixed values are applied here rather than trusted from the client:
    a field the form does not show is a field a request can still carry, and
    "hidden" would otherwise mean "hidden from honest callers".
    """
    by_key = {field.key: field for field in entry.fields}
    unexpected = sorted(set(submitted) - set(by_key))
    problems: list[dict[str, str]] = [
        {"path": f"values.{key}", "message": "This entry has no such field."} for key in unexpected
    ]

    effective: dict[str, Any] = {}
    for key, field in by_key.items():
        if field.fixed_value is not None:
            effective[key] = field.fixed_value
            continue
        if key in submitted and submitted[key] not in (None, ""):
            effective[key] = submitted[key]
        elif field.default_value is not None:
            effective[key] = field.default_value
        elif field.required:
            problems.append({"path": f"values.{key}", "message": f"'{field.label}' is required."})

    effective = _coerce_submitted(by_key, effective, problems)
    if problems:
        raise SubmissionRefused(problems)

    compiled = load_compiled(session, entry.pipeline_revision_id)
    bindings = [
        FieldBinding(
            key=field.key,
            # Coerced, not cast: the column carries a CHECK constraint from the
            # same enum, so a value outside it cannot be in the database.
            target=BindingTarget(field.binding_target),
            stage=field.binding_stage,
            step=field.binding_step,
            binding_key=field.binding_key,
            value_type=field.binding_value_type,
        )
        for field in entry.fields
    ]
    bound = apply_bindings(compiled, bindings, effective)
    return BoundPlan(
        entry=entry,
        pipeline=bound.pipeline,
        values=bound.values,
        submitted=effective,
    )
