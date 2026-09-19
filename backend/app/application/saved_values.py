"""Keeping a filled-in value, so nobody types it twice.

A `CustomReplicateRule` is four fields, two of them regular expressions, and a
researcher who runs the same analysis every week retypes all four every week.
That is what `saved_values` is for, and the table has been in the schema with
nothing writing to it since the base migration.

Three decisions.

**A saved value belongs to a person, not to an entry.** The unique key is
`(user, type_key, container, name)`. The same rule is useful against every
publication that asks for that type, and scoping it to the entry it was first
typed into would make somebody save it again for the next one.

**The schema is stored with the value.** Same rule as the publication field:
the definition lives in a pipeline document, documents are superseded, and a
value saved in March has to keep meaning what it meant in March. Storing the
type's *name* instead would let a definition change turn a saved value into
something that no longer validates, with nothing recording what it once was.

**A value is validated before it is kept, and again when it is used.** Kept
values are not trusted on the way back in: they were coerced against the
schema frozen at *save* time, and the field they are being used in froze its
own schema at *publish* time. Those can differ, and the difference is exactly
what a researcher needs told — "this saved rule no longer fits this form" is a
sentence; a container failing an hour later is not.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.application.pipelines import default_project_id
from app.domain import types
from app.domain.errors import Conflict, ValidationFailed
from app.infrastructure.db.models import SavedValue

CONTAINERS = ("single", "list", "map")
NAME_MAX = 256


class SavedValueRejected(ValidationFailed):
    code = "saved_value.invalid"


class NameTaken(Conflict):
    code = "saved_value.name_taken"


def list_saved(
    session: Session, *, user_id: uuid.UUID, type_key: str | None = None
) -> list[SavedValue]:
    """A person's saved values, newest first.

    Filtered by type when a form asks, because the picker on a field should
    offer the rules that fit it and not every value the researcher has ever
    kept.
    """
    query = select(SavedValue).where(SavedValue.user_id == user_id)
    if type_key:
        query = query.where(SavedValue.type_key == type_key)
    return list(session.execute(query.order_by(SavedValue.updated_at.desc())).scalars())


def get_saved(session: Session, value_id: uuid.UUID, *, user_id: uuid.UUID) -> SavedValue | None:
    """Somebody's saved value, or nothing.

    Another person's is indistinguishable from one that does not exist, as
    their runs and artifacts are.
    """
    saved = session.get(SavedValue, value_id)
    if saved is None or saved.user_id != user_id:
        return None
    return saved


def save_value(
    session: Session,
    *,
    user_id: uuid.UUID,
    type_key: str,
    type_schema: dict[str, Any],
    name: str,
    value: Any,
    container: str = "single",
) -> SavedValue:
    """Validate a value against its type and keep it under a name."""
    clean = _clean_name(name)
    if container not in CONTAINERS:
        raise SavedValueRejected(f"'{container}' is not a container this platform knows.")
    if not type_schema:
        raise SavedValueRejected(
            "A value can only be saved against a type, and this field has none."
        )
    coerced = types.coerce(value, type_schema, path=type_key)

    saved = SavedValue(
        project_id=default_project_id(session),
        user_id=user_id,
        type_key=type_key,
        type_schema=type_schema,
        container=container,
        name=clean,
        value={"value": coerced},
    )
    session.add(saved)
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError as error:
        if "uq_saved_values" not in str(error.orig):
            raise
        # No expunge: rolling the savepoint back has already removed the
        # pending object, and asking again raises an unrelated error on top of
        # the one worth reporting.
        raise NameTaken(
            f"You already have a {type_key} called '{clean}'. Rename it, or update that one.",
            details={"name": clean, "type_key": type_key},
        ) from error
    return saved


def update_saved(
    session: Session,
    saved: SavedValue,
    *,
    name: str | None = None,
    value: Any = None,
    # Distinguishes "leave the value alone" from "set it to null", which a
    # rename-only PATCH would otherwise be unable to say.
    has_value: bool = False,
) -> SavedValue:
    """Rename a saved value, replace what is in it, or both.

    Re-validated against the schema stored *with it*, not against whatever
    the type says now: this is the value's own frozen meaning, and editing it
    must not quietly migrate it to a newer definition.
    """
    if name is not None:
        saved.name = _clean_name(name)
    if has_value:
        saved.value = {"value": types.coerce(value, saved.type_schema, path=saved.type_key)}
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError as error:
        if "uq_saved_values" not in str(error.orig):
            raise
        raise NameTaken(
            f"You already have a {saved.type_key} called '{saved.name}'.",
            details={"name": saved.name, "type_key": saved.type_key},
        ) from error
    return saved


def delete_saved(session: Session, saved: SavedValue) -> None:
    """Remove it. A saved value is a convenience, so deletion is a deletion.

    Nothing points at it: a run records the value it was submitted with, not
    the saved value it came from, so deleting one cannot orphan history.
    """
    session.delete(saved)
    session.flush()


def usable_in(saved: SavedValue, field_schema: dict[str, Any] | None) -> tuple[bool, str | None]:
    """Whether this saved value still fits the field offering it.

    The two schemas were frozen at different moments — the value at save time,
    the field at publish time — so they can legitimately disagree. Saying so
    is a sentence; letting it through is a container that fails an hour later.
    """
    if not field_schema:
        return False, "This field does not take a saved value."
    if field_schema.get("key") != saved.type_key:
        return False, f"This field asks for {field_schema.get('key')}, not {saved.type_key}."
    try:
        types.coerce(saved.value.get("value"), field_schema, path=saved.type_key)
    except types.ValueRejected as rejected:
        first = rejected.problems[0]
        return False, (
            f"'{saved.name}' no longer fits this field: {first['path']} — {first['message']}"
        )
    return True, None


def _clean_name(name: str) -> str:
    clean = (name or "").strip()
    if not clean:
        raise SavedValueRejected("A saved value needs a name.")
    if len(clean) > NAME_MAX:
        raise SavedValueRejected(f"A name cannot be longer than {NAME_MAX} characters.")
    return clean
