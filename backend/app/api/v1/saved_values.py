"""Saved values: what a researcher keeps so they do not type it twice.

Scoped to the caller throughout. A saved value is personal — not shared, not
project-wide — so there is no parameter anywhere here that names a user, and
somebody else's value is a 404 rather than a 403.

The **schema is never taken from the request**. Saving happens against a
catalog entry's field, and that field's frozen `type_schema` is what the value
is validated against. A client that could supply its own schema could save
anything under any type name, and the picker on the next form would offer it.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, Db
from app.api.schemas import (
    Page,
    SavedValueResponse,
    SaveValueRequest,
    UpdateSavedValueRequest,
)
from app.application.publications import catalog_entry
from app.application.saved_values import (
    delete_saved,
    get_saved,
    list_saved,
    save_value,
    update_saved,
    usable_in,
)
from app.infrastructure.db.models import SavedValue

router = APIRouter(prefix="/saved-values", tags=["saved values"])


def _response(saved: SavedValue, *, field_schema: dict | None = None) -> SavedValueResponse:
    usable, reason = (True, None) if field_schema is None else usable_in(saved, field_schema)
    return SavedValueResponse(
        id=saved.id,
        type_key=saved.type_key,
        name=saved.name,
        container=saved.container,
        value=(saved.value or {}).get("value"),
        type_schema=saved.type_schema,
        created_at=saved.created_at,
        updated_at=saved.updated_at,
        usable=usable,
        unusable_reason=reason,
    )


def _mine_or_404(db: Db, value_id: uuid.UUID, principal: CurrentUser) -> SavedValue:
    saved = get_saved(db, value_id, user_id=principal.user_id)
    if saved is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "saved_value.not_found", "message": "No such saved value."},
        )
    return saved


def _field_or_404(db: Db, slug: str, field_key: str):
    entry = catalog_entry(db, slug=slug)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "catalog.not_found", "message": "No such catalog entry."},
        )
    field = next((item for item in entry.fields if item.key == field_key), None)
    if field is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "catalog.no_such_field", "message": "This entry has no such field."},
        )
    return field


@router.get("", response_model=Page[SavedValueResponse])
def list_my_saved_values(
    db: Db,
    principal: CurrentUser,
    type_key: str | None = None,
    entry: str | None = None,
    field_key: str | None = None,
) -> Page[SavedValueResponse]:
    """The caller's saved values.

    Given an entry and a field, each is also checked against *that field's*
    frozen schema, so a form can grey out a rule that no longer fits rather
    than offering one that will be refused on submission.
    """
    field_schema = None
    if entry and field_key:
        field = _field_or_404(db, entry, field_key)
        field_schema = field.type_schema
        type_key = type_key or (field_schema or {}).get("key")

    values = list_saved(db, user_id=principal.user_id, type_key=type_key)
    return Page[SavedValueResponse](
        items=[_response(saved, field_schema=field_schema) for saved in values],
        total=len(values),
    )


@router.post("", response_model=SavedValueResponse, status_code=status.HTTP_201_CREATED)
def save(
    payload: SaveValueRequest,
    db: Db,
    principal: CurrentUser,
    entry: str,
) -> SavedValueResponse:
    """Keep what is in a field, under a name, for next time.

    `entry` names the catalog entry the value was filled in against; the
    field's own frozen schema is what it is validated and stored with.
    """
    field = _field_or_404(db, entry, payload.field_key)
    if not (field.save_policy or {}).get("saveable"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "saved_value.not_saveable",
                "message": f"'{field.label}' is not a field whose value can be saved.",
            },
        )
    saved = save_value(
        db,
        user_id=principal.user_id,
        type_key=str((field.type_schema or {}).get("key") or field.type_ref or field.field_type),
        type_schema=field.type_schema,
        name=payload.name,
        value=payload.value,
        container=payload.container,
    )
    return _response(saved)


@router.patch("/{value_id}", response_model=SavedValueResponse)
def update(
    value_id: uuid.UUID,
    payload: UpdateSavedValueRequest,
    db: Db,
    principal: CurrentUser,
) -> SavedValueResponse:
    """Rename it, replace what is in it, or both."""
    saved = _mine_or_404(db, value_id, principal)
    update_saved(
        db,
        saved,
        name=payload.name,
        value=payload.value,
        has_value=payload.replace_value,
    )
    return _response(saved)


@router.delete("/{value_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove(value_id: uuid.UUID, db: Db, principal: CurrentUser) -> None:
    """Delete it.

    A real delete, not a soft one: a run records the value it was submitted
    with rather than the saved value it came from, so nothing is orphaned.
    """
    delete_saved(db, _mine_or_404(db, value_id, principal))
