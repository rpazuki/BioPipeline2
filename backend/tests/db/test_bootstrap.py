"""Deployment bootstrap must not reset, promote, or seed extra accounts."""

import uuid

import pytest
from sqlalchemy import func, select

from app.application.auth import PasswordTooWeak, authenticate, create_user
from app.bootstrap import create_administrator
from app.infrastructure.db.models import User

pytestmark = pytest.mark.db
PASSWORD = "bootstrap-test-password"


def email() -> str:
    return f"bootstrap-{uuid.uuid4().hex}@example.org"


def test_creates_only_one_local_administrator(db):
    address = email()
    before = db.scalar(select(func.count()).select_from(User))
    assert create_administrator(db, email=address, display_name="Lab admin", password=PASSWORD)
    user = authenticate(db, email=address, password=PASSWORD)
    assert user.role == "admin"
    assert user.auth_provider == "local"
    assert db.scalar(select(func.count()).select_from(User)) == before + 1


def test_repeat_is_case_insensitive_and_does_not_reset_password(db):
    address = email()
    create_administrator(db, email=address, display_name="Original", password=PASSWORD)
    assert not create_administrator(
        db, email=address.upper(), display_name="Replacement", password="different-password"
    )
    assert authenticate(db, email=address, password=PASSWORD).display_name == "Original"


@pytest.mark.parametrize("role,active", [("researcher", True), ("admin", False)])
def test_existing_account_is_not_promoted_or_reactivated(db, role, active):
    address = email()
    uid = create_user(db, email=address, display_name="Existing", password=PASSWORD, role=role)
    user = db.get(User, uid)
    user.is_active = active
    db.flush()
    with pytest.raises(ValueError, match="non-admin or inactive"):
        create_administrator(db, email=address, display_name="Admin", password=PASSWORD)
    assert user.role == role
    assert user.is_active == active


def test_weak_password_creates_no_account(db):
    address = email()
    with pytest.raises(PasswordTooWeak):
        create_administrator(db, email=address, display_name="Admin", password="short")
    assert db.scalar(select(User).where(User.email == address)) is None
