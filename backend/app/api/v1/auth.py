"""Sign in, sign out, and inspect the current session."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import Config, CurrentUser, Db, get_settings, require_csrf
from app.api.schemas import ChangePasswordRequest, LoginRequest, SessionResponse
from app.application.auth import (
    authenticate,
    change_password,
    end_session,
    start_session,
)
from app.domain.enums import UserRole
from app.settings import Settings

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_ttl_hours * 3600,
        # The token is never readable by page scripts, so an XSS bug cannot
        # exfiltrate a session even though it could act within one.
        httponly=True,
        secure=settings.secure_cookies,
        samesite=settings.cookie_samesite,
        path=f"{settings.base_path}/" if settings.base_path else "/",
    )


@router.post("/login", response_model=SessionResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Db,
    settings: Annotated[Settings, Depends(get_settings)],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> SessionResponse:
    user = authenticate(
        db,
        email=payload.email,
        password=payload.password,
        lockout_threshold=settings.login_lockout_threshold,
        lockout_minutes=settings.login_lockout_minutes,
    )
    token, _row = start_session(
        db,
        user,
        ttl_hours=settings.session_ttl_hours,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    _set_cookie(response, token, settings)
    return SessionResponse(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=UserRole(user.role),
        # Said at sign-in, not discovered by being refused: an account still
        # on the password an administrator generated should be shown the
        # change-password form, not an error on whatever they clicked first.
        must_change_password=user.must_change_password,
    )


@router.post("/logout", status_code=204)
def logout(principal: CurrentUser, db: Db, response: Response, settings: Config) -> None:
    end_session(db, principal.session_id)
    response.delete_cookie(
        settings.session_cookie_name,
        path=f"{settings.base_path}/" if settings.base_path else "/",
    )


@router.get("/session", response_model=SessionResponse)
def session(principal: CurrentUser) -> SessionResponse:
    return SessionResponse(
        user_id=principal.user_id,
        email=principal.email,
        display_name=principal.display_name,
        role=UserRole(principal.role),
        must_change_password=principal.must_change_password,
    )


@router.post("/change-password", status_code=204)
def change_own_password(payload: ChangePasswordRequest, principal: CurrentUser, db: Db) -> None:
    """Change a password, which invalidates every session it authorised --
    including this one. The client must sign in again, which is the point."""
    change_password(
        db,
        principal.user_id,
        current=payload.current_password,
        replacement=payload.new_password,
    )
