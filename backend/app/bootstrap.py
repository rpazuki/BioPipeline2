"""Create a local administrator without development seed accounts."""

from __future__ import annotations

import argparse
import getpass

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.application.auth import create_user
from app.domain.enums import UserRole
from app.domain.errors import DomainError
from app.infrastructure.db.models import User
from app.settings import load_settings


def create_administrator(db: Session, *, email: str, display_name: str, password: str) -> bool:
    """Create one administrator; repeats never change an existing account."""
    email = email.strip()
    if not email or "@" not in email or len(email) > 320:
        raise ValueError("Supply a valid administrator email (at most 320 characters).")
    if not display_name.strip() or len(display_name) > 256:
        raise ValueError("Supply a display name between 1 and 256 characters.")
    existing = db.scalar(select(User).where(func.lower(User.email) == email.lower()))
    if existing is not None:
        if existing.role != UserRole.ADMIN or not existing.is_active:
            raise ValueError("This email belongs to an existing non-admin or inactive account.")
        return False
    create_user(
        db, email=email, display_name=display_name.strip(), password=password, role=UserRole.ADMIN
    )
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--display-name", default="Administrator")
    args = parser.parse_args()
    settings = load_settings()
    password = getpass.getpass("Administrator password (at least 12 characters): ")
    if password != getpass.getpass("Confirm password: "):
        print("Passwords do not match; no account created.")
        return 2
    engine = create_engine(str(settings.database_url))
    try:
        with Session(engine) as db, db.begin():
            created = create_administrator(
                db, email=args.email, display_name=args.display_name, password=password
            )
        print("Administrator created." if created else "Administrator already exists; unchanged.")
        return 0
    except (ValueError, DomainError) as error:
        print(str(error))
        return 2
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
