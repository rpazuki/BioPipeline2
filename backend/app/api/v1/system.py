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
from app.api.deps import Config, Db
from app.api.schemas import HealthResponse, ReadyResponse

router = APIRouter(tags=["system"])


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
