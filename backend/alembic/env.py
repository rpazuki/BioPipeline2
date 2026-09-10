"""Alembic environment.

The database URL always comes from :mod:`app.settings`, never from
``alembic.ini``. That keeps one source of configuration and stops a migration
being run against a different database than the application uses.
"""

from __future__ import annotations

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from app.infrastructure.db.models import Base
from app.settings import load_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

config.set_main_option("sqlalchemy.url", str(load_settings().database_url))


def include_object(obj, name, type_, reflected, compare_to) -> bool:
    """Keep autogenerate away from objects Alembic cannot model.

    The immutability trigger and its function are created by an explicit
    migration; autogenerate would otherwise try to drop what it cannot see.
    """
    return not (type_ == "table" and name in {"alembic_version"})


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            include_object=include_object,
        )
        # pg_trgm must exist before any migration creates a trigram index.
        connection.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
