"""One error shape, for every failure.

A machine-readable envelope with a stable ``code``, so a client can branch on
what went wrong rather than matching prose:

```json
{"error": {"code": "pipeline.compilation_failed",
           "message": "Pipeline failed to compile with 2 error(s).",
           "details": {"errors": [...]},
           "request_id": "req_..."}}
```

``request_id`` is on every response, success or failure, and in every log line
for that request. Without it, "my run failed at about eleven" is not something
anyone can trace.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.domain.errors import (
    DomainError,
    ExpressionError,
    InvalidTransition,
    TerminalStateModified,
    ValidationFailed,
)

REQUEST_ID_HEADER = "X-Request-ID"


def envelope(
    *, code: str, message: str, details: dict[str, Any] | None, request_id: str
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "request_id": request_id,
        }
    }


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")


# Domain failures carry their own codes; the mapping to HTTP lives here, in
# the only layer that should know what HTTP is.
_STATUS_BY_ERROR: dict[type[DomainError], int] = {
    ValidationFailed: status.HTTP_422_UNPROCESSABLE_CONTENT,
    ExpressionError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    InvalidTransition: status.HTTP_409_CONFLICT,
    TerminalStateModified: status.HTTP_409_CONFLICT,
}


def status_for(error: DomainError) -> int:
    for kind, code in _STATUS_BY_ERROR.items():
        if isinstance(error, kind):
            return code
    return status.HTTP_400_BAD_REQUEST


async def domain_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, DomainError)
    return JSONResponse(
        status_code=status_for(exc),
        content=envelope(
            code=exc.code,
            message=exc.message,
            details=exc.details,
            request_id=_request_id(request),
        ),
    )


async def http_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, HTTPException)
    detail = exc.detail
    code = "http.error"
    message = str(detail)
    details: dict[str, Any] = {}
    if isinstance(detail, dict):
        code = str(detail.get("code", code))
        message = str(detail.get("message", ""))
        details = dict(detail.get("details") or {})
    return JSONResponse(
        status_code=exc.status_code,
        content=envelope(
            code=code, message=message, details=details, request_id=_request_id(request)
        ),
        headers=getattr(exc, "headers", None),
    )


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Request validation, reported per field.

    The path is normalised so a client can point at the offending input
    directly rather than parsing a nested list of tuples.
    """
    assert isinstance(exc, RequestValidationError)
    problems = [
        {
            "path": ".".join(str(part) for part in error["loc"][1:]) or str(error["loc"][0]),
            "message": error["msg"],
        }
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content=envelope(
            code="request.invalid",
            message="The request could not be understood.",
            details={"errors": problems},
            request_id=_request_id(request),
        ),
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """The last resort.

    Deliberately says nothing about the exception: an unhandled error is by
    definition one nobody reasoned about, so its message could contain
    anything. The request id is how it is tied to the log line that has the
    traceback.
    """
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=envelope(
            code="internal.error",
            message="The request failed unexpectedly.",
            details={},
            request_id=_request_id(request),
        ),
    )
