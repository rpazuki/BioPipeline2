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

from app.application.audit import RequestContext, as_ip
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


# The only two things a session may do while it is carrying a password an
# administrator chose: find out who it is, and change that password.
PASSWORD_CHANGE_ALLOWED = frozenset({"/auth/session", "/auth/change-password", "/auth/logout"})


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
    _require_own_password(request, principal)
    return principal


def _require_own_password(request: Request, principal: Principal) -> None:
    """Refuse everything but the password change, while the password is not theirs.

    An account an administrator created has a password the administrator
    knows. Letting that session do anything else would make a temporary fact
    — "somebody read it to me down the phone" — a standing one.
    """
    if not principal.must_change_password:
        return
    if any(request.url.path.endswith(allowed) for allowed in PASSWORD_CHANGE_ALLOWED):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": "auth.password_change_required",
            "message": (
                "This account is still using the password it was created with. "
                "Choose your own before doing anything else."
            ),
        },
    )


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


def request_context(
    request: Request, principal: Annotated[Principal, Depends(current_principal)]
) -> RequestContext:
    """What the audit needs and the domain must not know.

    Assembled once, here, so a handler recording a change cannot accidentally
    record it without the actor — which is the only field that makes an audit
    row worth keeping.
    """
    client = request.client
    return RequestContext(
        actor_id=principal.user_id,
        request_id=getattr(request.state, "request_id", None),
        ip_address=as_ip(client.host if client else None),
        user_agent=request.headers.get("user-agent", "")[:512] or None,
    )


CurrentUser = Annotated[Principal, Depends(current_principal)]
Audit = Annotated[RequestContext, Depends(request_context)]
AdminUser = Annotated[Principal, Depends(require_admin)]
Db = Annotated[Session, Depends(get_db)]
Config = Annotated[Settings, Depends(get_settings)]
