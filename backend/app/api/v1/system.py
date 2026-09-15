"""Health and readiness.

Both unauthenticated: a reverse proxy and a container runtime need them, and
neither can present a session. They therefore say as little as possible --
enough to route traffic, nothing an unauthenticated caller could use to
profile the deployment.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app import __version__
from app.api.deps import CSRF_HEADER, CSRF_VALUE, Config, Db
from app.api.schemas import ClientConfigResponse, HealthResponse, ReadyResponse

router = APIRouter(tags=["system"])
# Served under the versioned prefix, unlike health and readiness: it is part
# of the API a client programs against, not an infrastructure probe.
config_router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness: is the process up.

    Touches nothing, so a database outage does not cause the runtime to kill
    otherwise-healthy processes and turn a recoverable problem into an outage.
    """
    return HealthResponse(status="ok", version=__version__)


@router.get("/ready", response_model=ReadyResponse)
def ready(db: Db, settings: Config, response: Response) -> ReadyResponse:
    """Readiness: can this process actually serve requests."""
    checks: dict[str, str] = {}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as error:
        checks["database"] = f"unavailable: {type(error).__name__}"

    for name, path in (
        ("artifact_root", settings.artifact_root),
        ("workspace_root", settings.workspace_root),
    ):
        checks[name] = "ok" if path.is_dir() else "missing"

    healthy = all(value == "ok" for value in checks.values())
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadyResponse(status="ok" if healthy else "degraded", checks=checks)


@config_router.get("/config", response_model=ClientConfigResponse)
def client_config(settings: Config) -> ClientConfigResponse:
    """What the browser is allowed to know before anyone signs in.

    One frontend build serves several deployments by reading this rather than
    baking values in, and the login page needs it before a session exists, so
    it is unauthenticated. The payload is an allowlist -- ``Settings.public()``
    -- not a filtered dump, so a setting added tomorrow is private because
    nobody named it here.

    The CSRF header is published rather than duplicated in the client: it is
    not a secret (the protection is that a cross-origin caller cannot set a
    custom header without a preflight we do not grant), and a client that
    guesses it wrong fails every write.
    """
    return ClientConfigResponse(
        **settings.public(),
        csrf_header=CSRF_HEADER,
        csrf_value=CSRF_VALUE,
    )
