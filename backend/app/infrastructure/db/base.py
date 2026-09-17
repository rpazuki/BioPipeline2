"""Declarative base, naming conventions, and shared column helpers.

Two things here are deliberate and load-bearing.

**Named constraints.** Document 04 requires every constraint to be named.
Alembic cannot generate a stable ``downgrade`` for anonymous constraints, and an
operator cannot act on ``violates check constraint "ck_1a2b3c"``. The naming
convention below makes every name derivable from the table and column.

**CHECK constraints instead of native enums.** ADR 0011 is still open; this
build implements the recommended option (G37). ``enum_check`` renders a
constraint straight from the Python enum, so the database and the API cannot
drift apart: adding a value is an ordinary migration, and Postgres never has to
drop an enum label, which it cannot do.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    MetaData,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.domain.enums import DomainEnum

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    type_annotation_map = {  # noqa: RUF012
        dict[str, Any]: JSONB,
        list[Any]: JSONB,
    }


def enum_check(column: str, enum: type[DomainEnum], *, name: str | None = None) -> CheckConstraint:
    """Render a named CHECK constraint from a domain enum."""
    return CheckConstraint(
        f"{column} IN ({enum.check_values()})",
        name=name or f"{column}_valid",
    )


# --- column helpers -------------------------------------------------------


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )


def uuid_fk(
    target: str,
    *,
    nullable: bool = False,
    ondelete: str = "RESTRICT",
    index: bool = False,
    use_alter: bool = False,
) -> Mapped[uuid.UUID]:
    """A UUID foreign key.

    ``use_alter`` is needed where two tables reference each other (a
    publication points at its current revision, and every revision points back
    at its publication), so the constraint is added after both tables exist.
    """
    return mapped_column(
        UUID(as_uuid=True),
        ForeignKey(target, ondelete=ondelete, use_alter=use_alter),
        nullable=nullable,
        index=index,
    )


def created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


def updated_at() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=text("now()"),
    )


def event_timestamp() -> Mapped[datetime]:
    """When a row in a history table was written, to the microsecond.

    ``now()`` in PostgreSQL is the *transaction* timestamp, so every row a
    single transaction writes shares it. That is right for a record of when
    something was true and wrong for a log: one scheduler tick can record a
    dropped backlog, a run created and a schedule paused, and rendered in
    timestamp order those three arrive shuffled, telling a story that did not
    happen. ``clock_timestamp()`` advances within the transaction.
    """
    return mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("clock_timestamp()")
    )


def timestamp(*, nullable: bool = True, index: bool = False) -> Mapped[datetime | None]:
    return mapped_column(DateTime(timezone=True), nullable=nullable, index=index)


def required_timestamp(*, index: bool = False) -> Mapped[datetime]:
    """A non-null, timezone-aware timestamp.

    Exists because `mapped_column(nullable=False)` on a `datetime` infers a
    *naive* column, and every comparison in this schema is against `now()`,
    which is aware. Mixing the two makes the result depend on the connection's
    TimeZone setting -- which for `schedule_fires.fire_at` would undermine the
    uniqueness guarantee that makes a schedule fire exactly once per window.
    """
    return mapped_column(DateTime(timezone=True), nullable=False, index=index)


def status_column(enum: type[DomainEnum], default: DomainEnum | None = None) -> Mapped[str]:
    return mapped_column(
        String(64),
        nullable=False,
        server_default=text(f"'{default.value}'") if default is not None else None,
    )


def slug_column() -> Mapped[str]:
    return mapped_column(String(128), nullable=False)


def jsonb(*, nullable: bool = False, default: str = "'{}'::jsonb") -> Mapped[dict[str, Any]]:
    return mapped_column(
        JSONB, nullable=nullable, server_default=text(default) if not nullable else None
    )


def nullable_jsonb() -> Mapped[Any]:
    """A JSON column where "absent" really means absent.

    ``none_as_null`` is the whole point. Without it SQLAlchemy persists Python
    ``None`` as JSON ``null``, which is a *value*: the column is not NULL, so a
    CHECK asking ``IS NULL`` never fires and "no fixed value" becomes
    indistinguishable from "a fixed value of null".

    Typed ``Any`` rather than ``dict``, because these columns hold whatever a
    field's value is — ``5``, ``"od600"``, a list, an object. Annotating them
    as dictionaries was wishful.
    """
    return mapped_column(JSONB(none_as_null=True), nullable=True)


def bytes_column(*, nullable: bool = False, default: int | None = None) -> Mapped[int]:
    return mapped_column(
        BigInteger,
        nullable=nullable,
        server_default=text(str(default)) if default is not None else None,
    )


SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]{0,126}[a-z0-9]$"


def slug_check(column: str = "slug") -> CheckConstraint:
    """Slugs appear in URLs and in storage keys, so they are tightly bounded."""
    return CheckConstraint(f"{column} ~ '{SLUG_PATTERN}'", name=f"{column}_format")
