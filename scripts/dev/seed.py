#!/usr/bin/env python3
"""Put enough in an empty database to sign in and run something.

Development and end-to-end testing only. It refuses to touch a production or
staging database, and it refuses to invent a password: a seeded account with a
well-known password is a back door that outlives the afternoon it was
convenient for, and this one would be an administrator.

Idempotent, so it can sit in front of a Playwright run without a guard.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.application.auth import create_user
from app.domain.enums import UserRole
from app.infrastructure.db.models import User
from app.settings import load_settings
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

ADMIN_EMAIL_ENV = "BP_SEED_ADMIN_EMAIL"
ADMIN_PASSWORD_ENV = "BP_SEED_ADMIN_PASSWORD"
RESEARCHER_EMAIL_ENV = "BP_SEED_RESEARCHER_EMAIL"
RESEARCHER_PASSWORD_ENV = "BP_SEED_RESEARCHER_PASSWORD"

MINIMUM_PASSWORD_LENGTH = 12


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--admin-email", default=os.environ.get(ADMIN_EMAIL_ENV, "admin@example.org")
    )
    parser.add_argument(
        "--researcher-email",
        default=os.environ.get(RESEARCHER_EMAIL_ENV, "researcher@example.org"),
    )
    args = parser.parse_args()

    settings = load_settings()
    if settings.environment in {"production", "staging"}:
        print(
            f"seed: refusing to seed a {settings.environment} database", file=sys.stderr
        )
        return 2

    admin_password = os.environ.get(ADMIN_PASSWORD_ENV)
    researcher_password = os.environ.get(RESEARCHER_PASSWORD_ENV) or admin_password
    if not admin_password:
        print(
            f"seed: set {ADMIN_PASSWORD_ENV} (at least {MINIMUM_PASSWORD_LENGTH} characters).\n"
            "There is no default on purpose: this account is an administrator.",
            file=sys.stderr,
        )
        return 2
    if len(admin_password) < MINIMUM_PASSWORD_LENGTH:
        print(
            f"seed: {ADMIN_PASSWORD_ENV} must be at least {MINIMUM_PASSWORD_LENGTH} characters",
            file=sys.stderr,
        )
        return 2

    engine = create_engine(str(settings.database_url))
    wanted = (
        (args.admin_email, "Seeded Admin", UserRole.ADMIN, admin_password),
        (
            args.researcher_email,
            "Seeded Researcher",
            UserRole.RESEARCHER,
            researcher_password,
        ),
    )

    try:
        with Session(engine) as session:
            for email, name, role, password in wanted:
                existing = session.execute(
                    select(User).where(User.email == email)
                ).scalar_one_or_none()
                if existing is not None:
                    print(f"seed: {email} already exists ({existing.role})")
                    continue
                assert password is not None
                create_user(
                    session,
                    email=email,
                    display_name=name,
                    password=password,
                    role=role,
                )
                print(f"seed: created {email} ({role})")
            session.commit()
    except OperationalError:
        # Sixty frames of psycopg traceback to say the database is not running
        # is not a useful development experience.
        where = str(settings.database_url).split("@")[-1]
        print(
            f"seed: no database at {where}. Run `make db-up && make migrate`.",
            file=sys.stderr,
        )
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
