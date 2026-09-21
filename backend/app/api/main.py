"""The FastAPI application.

Assembled here rather than at import time, so tests can build an app against a
different database without process-wide state.

The API process serves HTTP and nothing else: no worker loop, no scheduler, no
reaper. Running background work inside the web process is convenient in
development and the reason the current system cannot scale past one replica --
two API processes would mean two schedulers.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import sessionmaker

from app import __version__
from app.api.errors import (
    REQUEST_ID_HEADER,
    domain_error_handler,
    envelope,
    http_error_handler,
    unhandled_error_handler,
    validation_error_handler,
)
from app.api.v1 import (
    admin,
    artifacts,
    auth,
    catalog,
    environments,
    pipelines,
    publications,
    runs,
    saved_values,
    schedules,
    storage,
    system,
    uploads,
)
from app.domain.errors import DomainError
from app.observability import configure_logging
from app.settings import Settings, load_settings

logger = logging.getLogger("biopipeline2.api")


def create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
    settings = settings or load_settings()
    engine = engine or create_engine(str(settings.database_url), pool_pre_ping=True)

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        # Served under a path prefix from the start, because retrofitting one
        # means auditing every generated URL, cookie path and redirect.
        root_path=settings.base_path,
        docs_url="/api/docs" if settings.environment != "production" else None,
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessions = sessionmaker(bind=engine, expire_on_commit=False)

    # Order matters, and Starlette builds the stack so that the *last*
    # middleware added is the outermost. The request-id layer is registered
    # first so CORS ends up outside it: an unhandled exception is turned into
    # a response here, below CORS, and therefore still comes back with the
    # headers a browser needs to read it. Handled by the framework's own
    # last-resort handler instead, it would be generated above CORS and reach
    # the page as an opaque network error with nothing in it.
    @app.middleware("http")
    async def attach_request_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """One id per request, echoed back and logged.

        Accepts a caller-supplied id so a trace survives a proxy hop, and
        generates one otherwise. Without it, "my run failed at about eleven"
        is not something anyone can follow through the logs -- which is
        precisely why the failing response has to carry it too, and why this
        catches rather than re-raising.
        """
        supplied = request.headers.get(REQUEST_ID_HEADER, "")[:64]
        request_id = supplied or f"req_{uuid.uuid4().hex}"
        request.state.request_id = request_id
        try:
            response = await call_next(request)
        except Exception:
            # As a field rather than only in the message: the id is what
            # joins this line to the response the person is holding, and a
            # field survives a grep that a sentence does not.
            logger.exception(
                "request failed: %s %s",
                request.method,
                request.url.path,
                extra={"request_id": request_id},
            )
            response = JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content=envelope(
                    code="internal.error",
                    message="The request failed unexpectedly.",
                    details={},
                    request_id=request_id,
                ),
            )
        response.headers[REQUEST_ID_HEADER] = request_id
        return response

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=[REQUEST_ID_HEADER],
        )

    app.add_exception_handler(DomainError, domain_error_handler)
    app.add_exception_handler(HTTPException, http_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)

    app.include_router(system.router)
    for router in (
        admin.router,
        auth.router,
        pipelines.router,
        publications.router,
        catalog.router,
        environments.router,
        runs.router,
        artifacts.router,
        schedules.router,
        saved_values.router,
        storage.router,
        uploads.router,
        system.config_router,
    ):
        app.include_router(router, prefix=settings.api_prefix)

    return app


app = create_app if False else None  # built by the ASGI entry point below


def get_app() -> FastAPI:  # pragma: no cover - process entry point
    configure_logging("api")
    return create_app()
