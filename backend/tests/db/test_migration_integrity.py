"""The migration must produce the schema the models describe.

Document 12 requires a fresh database to migrate to head and the models to
agree with the migrations. These tests guard specific ways that agreement
broke during development.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.infrastructure.db.models import Base

pytestmark = pytest.mark.db


def test_every_model_table_exists_in_the_database(db: Session):
    declared = set(Base.metadata.tables)
    actual = {
        row[0]
        for row in db.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
            )
        ).all()
    }
    missing = declared - actual
    assert not missing, f"tables declared on the models but absent from the database: {missing}"


@pytest.mark.parametrize(
    "constraint",
    [
        "fk_publications_current_revision_id_publication_revisions",
        "fk_run_task_attempts_log_artifact_id_artifacts",
    ],
)
def test_circular_foreign_keys_are_actually_created(db: Session, constraint: str):
    """Alembic autogenerate silently omits ``use_alter`` foreign keys.

    Both of these went missing once already: the tables were created, the
    models declared the relationship, and the columns had no referential
    integrity at all. They are added by explicit statements in the migration,
    so this test is what proves those statements are still there.
    """
    found = db.execute(
        text("SELECT 1 FROM pg_constraint WHERE conname = :name AND contype = 'f'"),
        {"name": constraint},
    ).scalar_one_or_none()
    assert found == 1, f"foreign key {constraint} is missing from the database"


def test_no_check_constraint_name_is_double_prefixed(db: Session):
    """The naming convention prepends ``ck_<table>_``; passing a full name
    once produced ``ck_run_task_dependencies_ck_run_task_dependencies_...``
    and a truncated hash suffix."""
    doubled = [
        row[0]
        for row in db.execute(
            # A regex, not LIKE: '_' is a single-character wildcard in LIKE,
            # so 'ck_%_ck_%' matches almost every constraint name.
            text(
                "SELECT conname FROM pg_constraint "
                "WHERE contype = 'c' AND connamespace = 'public'::regnamespace "
                "AND conname ~ '^ck_.+_ck_'"
            )
        ).all()
    ]
    assert not doubled, f"double-prefixed constraint names: {doubled}"


def test_the_trigram_extension_is_installed(db: Session):
    installed = db.execute(
        text("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")
    ).scalar_one_or_none()
    assert installed == 1


def test_uuid_generation_is_available_without_an_extension(db: Session):
    """``gen_random_uuid()`` is built in from PostgreSQL 13, so the schema
    needs no pgcrypto dependency."""
    value = db.execute(text("SELECT gen_random_uuid()")).scalar_one()
    assert value is not None
