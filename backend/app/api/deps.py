"""Request dependencies: the database session, the principal, and CSRF.

Authorization is enforced here and nowhere else in the HTTP layer, so a route
cannot forget it by omission: a handler either declares a dependency that
produces a principal, or it is public by explicit choice.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.application.auth import AuthenticationFailed, Principal, resolve_session
from app.settings import Settings

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
CSRF_HEADER = "X-Requested-With"
CSRF_VALUE = "BioPipeline2"


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Iterator[Session]:
    """A session per request, committed on success and rolled back on failure.

    The route decides what to do; the transaction boundary is here so no
    handler can leave one half-applied.
    """
    factory = request.app.state.sessions
    session: Session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _unauthenticated(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "auth.required", "message": message},
    )


def require_csrf(request: Request) -> None:
    """Reject unsafe cross-origin requests.

    Cookie authentication means a browser attaches credentials to any request
    it is induced to make, so a state-changing request needs proof it came
    from our own code. A custom header cannot be set cross-origin without a
    CORS preflight we do not grant, which makes it sufficient and costs no
    token plumbing.
    """
    if request.method in SAFE_METHODS:
        return
    settings: Settings = request.app.state.settings
    if not settings.csrf_protection:
        return
    if request.headers.get(CSRF_HEADER) != CSRF_VALUE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "auth.csrf_required",
                "message": (f"State-changing requests must carry the {CSRF_HEADER} header."),
            },
        )


def current_principal(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> Principal:
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise _unauthenticated("This endpoint requires a signed-in user.")
    try:
        principal = resolve_session(
            db,
            token,
            idle_timeout_hours=settings.session_idle_timeout_hours,
            ttl_hours=settings.session_ttl_hours,
        )
    except AuthenticationFailed as error:
        raise _unauthenticated(error.message) from error
    request.state.principal = principal
    return principal


def require_admin(
    principal: Annotated[Principal, Depends(current_principal)],
) -> Principal:
    """Admin-only.

    Authorization is enforced on the backend whatever the UI shows: hiding a
    control is a usability choice, not a security one.
    """
    if not principal.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "auth.forbidden",
                "message": "This endpoint is restricted to administrators.",
            },
        )
    return principal


CurrentUser = Annotated[Principal, Depends(current_principal)]
AdminUser = Annotated[Principal, Depends(require_admin)]
Db = Annotated[Session, Depends(get_db)]
Config = Annotated[Settings, Depends(get_settings)]
