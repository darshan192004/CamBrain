"""Map domain errors to the single API error envelope (API §4).

Envelope shape: {"error": {"code", "message", "field", "correlation_id"}}.
One shape for every failure so the Tauri shell can render errors without
parsing per-endpoint quirks.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import (
    AuthError as CoreAuthError,
)
from app.core.errors import (
    CamBrainError,
    ConflictError,
    NotFoundError,
    StorageError,
    ValidationError,
)


def _correlation_id(request: Request) -> str:
    return getattr(request.state, "correlation_id", "unknown")


def _envelope(
    code: str, message: str, request: Request, field: str | None = None
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "field": field,
            "correlation_id": _correlation_id(request),
        }
    }


def install_error_handlers(app: FastAPI) -> None:
    """Register domain-exception handlers producing the error envelope."""

    from app.api.auth import AccountLockedError, AuthError, ForbiddenError

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        """Framework-raised errors (404 unknown route, 405) use the same envelope."""
        code = {
            401: "UNAUTHENTICATED",
            403: "FORBIDDEN",
            404: "NOT_FOUND",
            405: "METHOD_NOT_ALLOWED",
            429: "RATE_LIMITED",
        }.get(exc.status_code, "BAD_REQUEST")
        message = exc.detail if isinstance(exc.detail, str) else "request failed"
        return JSONResponse(status_code=exc.status_code, content=_envelope(code, message, request))

    @app.exception_handler(AuthError)
    async def _auth(request: Request, exc: AuthError) -> JSONResponse:
        return JSONResponse(
            status_code=401, content=_envelope("UNAUTHENTICATED", str(exc), request)
        )

    @app.exception_handler(AccountLockedError)
    async def _locked(request: Request, exc: AccountLockedError) -> JSONResponse:
        return JSONResponse(status_code=423, content=_envelope("ACCOUNT_LOCKED", str(exc), request))

    @app.exception_handler(ForbiddenError)
    async def _forbidden(request: Request, exc: ForbiddenError) -> JSONResponse:
        return JSONResponse(status_code=403, content=_envelope("FORBIDDEN", str(exc), request))

    @app.exception_handler(CoreAuthError)
    async def _core_auth(request: Request, exc: CoreAuthError) -> JSONResponse:
        return JSONResponse(
            status_code=401, content=_envelope("UNAUTHENTICATED", str(exc), request)
        )

    @app.exception_handler(NotFoundError)
    async def _not_found(request: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content=_envelope("NOT_FOUND", str(exc), request))

    @app.exception_handler(ValidationError)
    async def _validation(request: Request, exc: ValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422, content=_envelope("VALIDATION_ERROR", str(exc), request)
        )

    @app.exception_handler(ConflictError)
    async def _conflict(request: Request, exc: ConflictError) -> JSONResponse:
        return JSONResponse(status_code=409, content=_envelope("CONFLICT", str(exc), request))

    @app.exception_handler(StorageError)
    async def _storage(request: Request, exc: StorageError) -> JSONResponse:
        return JSONResponse(status_code=500, content=_envelope("INTERNAL", str(exc), request))

    @app.exception_handler(CamBrainError)
    async def _domain(request: Request, exc: CamBrainError) -> JSONResponse:
        return JSONResponse(status_code=500, content=_envelope("INTERNAL", str(exc), request))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:  # noqa: ARG001
        """Last-resort 500: envelope with correlation id, never the traceback."""
        return JSONResponse(
            status_code=500,
            content=_envelope("INTERNAL", "internal server error", request),
        )
